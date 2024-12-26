import requests
import json
import random
import time
import toml
import logging
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log", mode="a", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# 初始化全局变量
config = {
    "selected_courses": {},
    "courses": [],
    "browser": "chrome",
    "username": "",
    "password": "",
    "allow_over_capacity": False,
}


def query_and_add_course(course):
    global token
    get_token_safe()
    headers = {"Authorization": token, "User-Agent": random.choice(["Mozilla/5.0"])}
    list_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/list"
    add_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/add"

    if not check_and_resolve_conflicts(course):
        return False

    try:
        response = requests.post(
            list_url,
            headers=headers,
            data={
                "KCH": course["KCH"],
                "JSH": course["JSH"],
                "teachingClassType": "XGKC",
            },
        )
        response.raise_for_status()
        rows = response.json().get("data", {}).get("list", {}).get("rows", [])
        for row in rows:
            if "JXBID" not in row or "secretVal" not in row:
                log.error(f"关键字段缺失: {row}")
                continue
            if row["numberOfSelected"] < row["classCapacity"] or config.get(
                "allow_over_capacity", False
            ):
                add_response = requests.post(
                    add_url,
                    headers=headers,
                    data={"clazzId": row["JXBID"], "secretVal": row["secretVal"]},
                )
                if add_response.status_code == 200:
                    config["selected_courses"][course["KCH"]] = course["JSH"]
                    log.info(f"课程 {course['KCH']} 添加成功!")
                    return True
    except Exception as e:
        log.error(f"查询或添加课程失败: {e}")
    return False


# 加载配置
def load_config(file_path="config.toml"):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            loaded_config = toml.load(file)
            global config
            config = loaded_config
            return config
    except FileNotFoundError:
        log.error(f"配置文件 {file_path} 未找到。")
        return None
    except toml.TomlDecodeError as e:
        log.error(f"配置文件解析失败: {e}")
        return None


# 在全局作用域中定义 token_lock
token_lock = Lock()


# 保存本地状态
def save_local_state_to_file(file_path="selected_courses.json"):
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(config.get("selected_courses", {}), file)
        log.info(f"本地状态保存到文件: {file_path}")
    except IOError as e:
        log.error(f"无法保存本地状态到文件: {e}")


# Token 有效性检查
def is_token_valid():
    try:
        response = requests.get(
            "https://jwxk.shu.edu.cn/test", headers={"Authorization": token}
        )
        return response.status_code == 200
    except:
        return False


# 安全获取 Token
def get_token_safe():
    global token
    with token_lock:
        if not is_token_valid():
            log.info("Token 无效，正在重新获取...")
            get_token()


# 浏览器登录获取 Token
def get_token():
    global token
    driver = None
    try:
        options = {
            "chrome": ChromeOptions(),
            "firefox": FirefoxOptions(),
            "edge": EdgeOptions(),
        }.get(config.get("browser").lower(), None)

        if options is None:
            log.error(f"不支持的浏览器: {config.get('browser')}")
            return

        options.add_argument("--headless")
        options.add_argument("--disable-gpu")

        driver_cls = {
            "chrome": webdriver.Chrome,
            "firefox": webdriver.Firefox,
            "edge": webdriver.Edge,
        }.get(config.get("browser").lower())

        driver = driver_cls(
            service={
                "chrome": ChromeService(),
                "firefox": FirefoxService(),
                "edge": EdgeService(),
            }[config.get("browser").lower()],
            options=options,
        )

        driver.get("https://jwxk.shu.edu.cn/")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        ).send_keys(config.get("username"))
        driver.find_element(By.ID, "password").send_keys(config.get("password"))
        driver.find_element(By.ID, "submit-button").click()
        time.sleep(2)

        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie["name"] == "Authorization":
                token = cookie["value"]
                log.info(f"成功获取 Token: {token}")
                return
    except Exception as e:
        log.error(f"获取 Token 出错: {e}")
    finally:
        if driver:
            driver.quit()


# 同步本地状态
def sync_local_state():
    global config
    url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/selected"
    headers = {"Authorization": token}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json().get("data", [])
        config["selected_courses"] = {course["KCH"]: course["JSH"] for course in data}
        config["selected_courses_cache"]["updated"] = True
        save_local_state_to_file()
        log.info("本地课程状态同步完成")
    except requests.exceptions.RequestException as e:
        log.error(f"同步本地状态失败: {e}")


# 时间段冲突检查
def check_and_resolve_conflicts(new_course):
    for kch, jsh in config.get("selected_courses", {}).items():
        if kch == new_course["KCH"] and jsh != new_course["JSH"]:
            log.warning(
                f"课程冲突: {kch}-{jsh} 与新课程 {new_course['KCH']}-{new_course['JSH']}"
            )
            return False
        if is_time_conflict(new_course, kch):
            log.warning(f"时间段冲突: 新课程 {new_course['KCH']} 与已选课程 {kch}")
            return False
    return True


def is_time_conflict(new_course, existing_course_kch):
    existing_course_time = get_time_slot(existing_course_kch)
    new_course_time = new_course.get("time_slot")
    return check_time_overlap(existing_course_time, new_course_time)


def check_time_overlap(time1, time2):
    start1, end1 = map(lambda t: int(t.replace(":", "")), time1.split("-"))
    start2, end2 = map(lambda t: int(t.replace(":", "")), time2.split("-"))
    return not (end1 <= start2 or end2 <= start1)


def get_time_slot(course_kch):
    course_time_slots = {
        "08305014": "08:00-10:00",
        "0830SY02": "10:00-12:00",
    }
    return course_time_slots.get(course_kch, "")


# 查询并尝试选课
def query_and_add_course(course):
    global token
    get_token_safe()
    headers = {"Authorization": token, "User-Agent": random.choice(["Mozilla/5.0"])}
    list_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/list"
    add_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/add"

    if not check_and_resolve_conflicts(course):
        return False

    try:
        response = requests.post(
            list_url,
            headers=headers,
            data={
                "KCH": course["KCH"],
                "JSH": course["JSH"],
                "teachingClassType": "XGKC",
            },
        )
        response.raise_for_status()
        rows = response.json().get("data", {}).get("list", {}).get("rows", [])
        for row in rows:
            if row["numberOfSelected"] < row["classCapacity"] or config.get(
                "allow_over_capacity", False
            ):
                add_response = requests.post(
                    add_url,
                    headers=headers,
                    data={"clazzId": row["JXBID"], "secretVal": row["secretVal"]},
                )
                if add_response.status_code == 200:
                    config["selected_courses"][course["KCH"]] = course["JSH"]
                    log.info(f"课程 {course['KCH']} 添加成功!")
                    return True
    except Exception as e:
        log.error(f"查询或添加课程失败: {e}")
    return False


# 主流程
def main():
    load_config()
    get_token_safe()
    sync_local_state()
    attempt = 0
    while True:
        attempt += 1
        log.info(f"第 {attempt} 次尝试...")
        courses_to_query = sorted(
            config.get("courses", []), key=lambda x: x.get("priority", float("inf"))
        )
        success = any(query_and_add_course(course) for course in courses_to_query)
        if success:
            log.info(f"抢课成功! 第 {attempt} 次尝试")
            break
        time.sleep(max(0, config.get("wait_time", 5.0) + random.uniform(-0.2, 0.2)))


if __name__ == "__main__":
    main()
