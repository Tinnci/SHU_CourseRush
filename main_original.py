import requests
import json
import random
import time
import toml
import glog as log
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def load_config(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return toml.load(file)

config = load_config("config.toml")
courses = config.get("courses", [])
username = config.get("username")
password = config.get("password")
use_multithreading = config.get("use_multithreading", False)
wait_time = config.get("wait_time", 5.0)
browser = config.get("browser", "edge")
# 允许超容量选择（还未踢人的情况）
allow_over_capacity = config.get("allow_over_capacity", False)

list_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/list"
add_url = "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/add"

token = None
user_agents = [
    "Mozilla/5.0 ... Safari/537.36",  # Truncated for brevity
]

def get_token():
    global token
    driver = None

    try:
        if browser == "chrome":
            chrome_options = ChromeOptions()
            # 禁用GPU加速，有时候GPU相关问题可能导致闪退，特别是在一些显卡驱动不太适配的情况下
            chrome_options.add_argument('--disable-gpu')
            # 以无头模式运行（如果业务逻辑允许），无头模式可以避免一些因界面渲染等导致的不稳定情况
            chrome_options.add_argument('--headless')
            # 禁用扩展，某些扩展可能与自动化脚本冲突或者本身存在问题，导致浏览器闪退
            chrome_options.add_argument('--disable-extensions')
            driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
        elif browser == "firefox":
            firefox_options = FirefoxOptions()
            driver = webdriver.Firefox(service=FirefoxService(), options=firefox_options)
        elif browser == "edge":
            edge_options = EdgeOptions()
            driver = webdriver.Edge(service=EdgeService(), options=edge_options)
        else:
            log.error(f"未识别的浏览器类型: {browser}")
            return

        driver.get("https://jwxk.shu.edu.cn/")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username")))
        driver.find_element(By.ID, "username").send_keys(username)
        driver.find_element(By.ID, "password").send_keys(password)

        submit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "submit-button")))
        time.sleep(1)
        submit_button.click()
        time.sleep(2)
        log.info("登陆成功，等待选择学期冷却...")
        time.sleep(10)
        
        # 进入选择学期页面，这里有10秒的冷却时间
        try:
            # 使用 XPath 按钮内的文本匹配「确 定」
            confirm_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(@class, 'el-button--primary') and .//span[text()='确 定']]")
                )
            )
            confirm_button.click()
            log.info("点击“确 定”按钮成功。")
        except (TimeoutException, NoSuchElementException) as e:
            log.error(f"未能找到或点击“确 定”按钮: {e}")

        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie['name'] == 'Authorization':
                token = cookie['value']
                break

        if token:
            log.info(f"获取到的 Token: {token}")
    except Exception as e:
        log.error(f"{browser.capitalize()} 浏览器发生错误: {e}")
    finally:
        if driver:
            driver.quit()

def query_and_add_course(course):
    global token
    headers = {"Authorization": token}
    headers["User-Agent"] = random.choice(user_agents)

    KCH = course.get("KCH")
    JSH = course.get("JSH")
    class_type = course.get("class_type", "XGKC")

    list_data = {
        "teachingClassType": class_type,
        "pageNumber": 1,
        "pageSize": 10,
        "KCH": KCH,
        "JSH": JSH
    }

    try:
        response = requests.post(list_url, headers=headers, data=list_data)
        response_data = response.json()

        if "data" in response_data and "list" in response_data["data"]:
            rows = response_data["data"]["list"].get("rows", [])
            for row in rows:
                if row.get("numberOfSelected") < row.get("classCapacity") or allow_over_capacity:
                    add_data = {
                        "clazzType": class_type,
                        "clazzId": row.get("JXBID"),
                        "secretVal": row.get("secretVal")
                    }
                    add_response = requests.post(add_url, headers=headers, data=add_data)
                    if add_response.status_code == 200:
                        log.info(f"课程 {KCH} 添加成功!")
                        return True
                    else:
                        log.warning(f"课程 {KCH} 添加失败，状态码: {add_response.status_code}")
                        if add_response.status_code == 401:
                            log.warning("Token 失效，正在更新 Token...")
                            get_token()
                else:
                    log.info(f"课程 {KCH} 已满，继续尝试...")
    except requests.exceptions.RequestException as e:
        log.error(f"请求失败: {e}")
    return False

def query_courses_multithread():
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(query_and_add_course, course) for course in courses]
        for future in as_completed(futures):
            if future.result():
                return True
    return False

def query_courses_singlethread():
    for course in courses:
        if query_and_add_course(course):
            return True
    return False

def main():
    get_token()
    attempt = 0
    while True:
        attempt += 1
        log.info(f"第 {attempt} 次尝试...")

        success = (
            query_courses_multithread()
            if use_multithreading
            else query_courses_singlethread()
        )

        if success:
            log.info(f"抢课成功! 第 {attempt} 次尝试")
            break

        fluctuated_wait_time = max(0, wait_time + random.uniform(-0.2, 0.2))
        log.info(f"等待时间: {fluctuated_wait_time:.2f} 秒")
        time.sleep(fluctuated_wait_time)

if __name__ == "__main__":
    main()
