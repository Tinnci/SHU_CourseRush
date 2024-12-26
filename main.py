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
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
import platform
import os

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

token = None  # 全局 token 变量


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
    """获取登录 token"""
    global token
    driver = None
    try:
        browser_type = config.get("browser").lower()
        options = get_browser_options(browser_type)
        driver_path = config.get("driver_path")
        
        if not driver_path:
            log.error("未找到浏览器驱动路径")
            return False
            
        # 创建浏览器实例
        driver_cls = getattr(webdriver, browser_type.capitalize())
        driver = driver_cls(options=options)
        
        # 设置页面加载超时
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
        
        log.info("正在访问登录页面...")
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                driver.get("https://jwxk.shu.edu.cn/")
                break
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    log.warning(f"页面加载失败，正在重试 ({retry_count}/{max_retries})")
                    time.sleep(2)
                else:
                    log.error(f"页面加载失败: {e}")
                    return False
        
        try:
            # 等待并填写登录表单
            username_element = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            username_element.clear()
            username_element.send_keys(config.get("username"))
            
            password_element = driver.find_element(By.ID, "password")
            password_element.clear()
            password_element.send_keys(config.get("password"))
            
            # 点击登录按钮
            submit_button = driver.find_element(By.ID, "submit-button")
            submit_button.click()
            
            # 等待登录完成并检查重定向
            WebDriverWait(driver, 10).until(
                lambda d: "jwxk.shu.edu.cn/xsxk" in d.current_url
            )
            
            # 获取 cookies
            cookies = driver.get_cookies()
            auth_cookie = next(
                (cookie for cookie in cookies if cookie["name"] == "Authorization"), 
                None
            )
            
            if auth_cookie:
                token = auth_cookie["value"]
                log.info("成功获取新的 token")
                return True
            else:
                # 尝试从 localStorage 获取 token
                try:
                    local_storage = driver.execute_script("return window.localStorage;")
                    if "token" in local_storage:
                        token = local_storage["token"]
                        log.info("从 localStorage 获取到 token")
                        return True
                except Exception as e:
                    log.warning(f"从 localStorage 获取 token 失败: {e}")
                
                log.error("未找到认证信息")
                return False
                
        except Exception as e:
            log.error(f"登录过程中出错: {e}")
            return False
            
    except Exception as e:
        log.error(f"获取 token 出错: {e}")
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                log.warning(f"关闭浏览器时出错: {e}")


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
    # 添加配置版本检查
    if not verify_config_version():
        log.warning("配置版本检查失败，继续执行可能存在风险")
        
    # TODO: Add configuration version check
    if not load_config():
        log.error("程序因配置问题无法继续运行")
        return

    # Verify browser driver availability
    if not verify_browser_setup():
        log.error("浏览器驱动程序未正确安装或配置")
        return

    # Initial authentication
    get_token_safe()
    if not token:
        log.error("无法获取登录凭证，请检查用户名密码是否正确")
        return

    # TODO: Add proper session management
    if not verify_session():
        log.error("会话验证失败")
        return

    # Sync local state
    if not sync_local_state():
        log.error("同步本地状态失败，请检查网络连接和登录状态")
        return

    # TODO: Add proper rate limiting
    attempt = 0
    while True:
        rate_limiter.wait()  # 添加限流控制
        attempt += 1
        log.info(f"第 {attempt} 次尝试...")

        # Verify system status before proceeding
        if not verify_system_status():
            log.error("选课系统当前不可用，等待重试...")
            time.sleep(30)
            continue

        courses_to_query = sorted(
            config.get("courses", []), 
            key=lambda x: x.get("priority", float("inf"))
        )

        if not courses_to_query:
            log.error("没有需要选择的课程，请在配置文件中添加课程信息")
            return

        # TODO: Implement proper course status verification
        success = any(query_and_add_course(course) for course in courses_to_query)
        
        if success:
            if verify_selection_result():
                log.info(f"抢课成功! 第 {attempt} 次尝试")
                break
            else:
                log.warning("课程选择可能未成功，将继续尝试")

        wait_time = max(0, config.get("wait_time", 5.0) + random.uniform(-0.2, 0.2))
        time.sleep(wait_time)

def verify_browser_setup():
    """验证浏览器驱动是否正确安装"""
    browser = config.get("browser", "").lower()
    
    # 验证浏览器类型
    if browser not in ["chrome", "firefox", "edge"]:
        log.error(f"不支持的浏览器类型: {browser}")
        log.info("支持的浏览器类型: chrome, firefox, edge")
        return False
    
    try:
        # 获取系统信息
        os_name = platform.system()
        log.info(f"当前系统: {os_name}")
        
        # 根据浏览器类型获取驱动
        driver_manager_map = {
            "chrome": ChromeDriverManager,
            "firefox": GeckoDriverManager,
            "edge": EdgeChromiumDriverManager
        }
        
        # 尝试获取驱动路径
        try:
            driver_path = driver_manager_map[browser]().install()
            log.info(f"驱动路径: {driver_path}")
            
            # 尝试创建浏览器实例来验证
            options = get_browser_options(browser)
            driver_cls = getattr(webdriver, browser.capitalize())
            driver = driver_cls(options=options)
            driver.quit()
            
            # 保存驱动路径到配置
            config["driver_path"] = driver_path
            log.info(f"{browser.capitalize()} 浏览器驱动验证成功")
            return True
            
        except Exception as e:
            log.error(f"驱动验证失败: {e}")
            return False
            
    except Exception as e:
        log.error(f"浏览器驱动验证失败: {str(e)}")
        return False

def get_browser_options(browser_type):
    """获取浏览器配置选项"""
    options_map = {
        "chrome": ChromeOptions,
        "firefox": FirefoxOptions,
        "edge": EdgeOptions
    }
    
    options = options_map[browser_type]()
    
    # 通用配置
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # 添加 SSL 相关配置
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--allow-insecure-localhost")
    
    # 浏览器特定配置
    if browser_type == "chrome":
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    elif browser_type == "firefox":
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        options.set_preference("network.stricttransportsecurity.preloadlist", False)
        options.set_preference("security.cert_pinning.enforcement_level", 0)
    elif browser_type == "edge":
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    
    return options

def verify_session():
    """验证当前会话是否有效"""
    global token
    
    if not token:
        log.error("未找到有效的会话 token")
        return False
        
    try:
        # 验证会话有效性
        response = requests.get(
            "https://jwxk.shu.edu.cn/xsxk/elective/shu/announce/info",
            headers={"Authorization": token},
            timeout=5
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("code") == 200:
                    log.info("会话验证成功")
                    return True
                else:
                    log.warning(f"会话验证失败: {data.get('msg', '未知错误')}")
            except json.JSONDecodeError:
                log.error("会话验证响应解析失败")
        else:
            log.error(f"会话验证请求失败: HTTP {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        log.error(f"会话验证网络请求失败: {e}")
        
    return False


def verify_system_status():
    """验证选课系统是否可用"""
    try:
        # 检查系统状态
        response = requests.get(
            "https://jwxk.shu.edu.cn/xsxk/elective/shu/system/status",
            headers={"Authorization": token},
            timeout=5
        )
        
        if response.status_code != 200:
            log.error(f"系统状态检查失败: HTTP {response.status_code}")
            return False
            
        try:
            data = response.json()
            if data.get("code") != 200:
                log.error(f"选课系统状态异常: {data.get('msg', '未知错误')}")
                return False
                
            system_info = data.get("data", {})
            
            # 检查选课时间
            if not system_info.get("isInElectiveTime", False):
                log.error("当前不在选课时间范围内")
                return False
                
            # 检查系统负载
            if system_info.get("systemLoad", 100) >= 95:
                log.warning("系统负载较高，可能影响选课")
                
            log.info("选课系统状态正常")
            return True
            
        except json.JSONDecodeError:
            log.error("系统状态响应解析失败")
            return False
            
    except requests.exceptions.RequestException as e:
        log.error(f"系统状态检查网络请求失败: {e}")
        return False


def verify_selection_result():
    """验证选课结果是否真实成功"""
    try:
        # 同步本地状态
        if not sync_local_state():
            log.error("无法同步课程状态，选课结果验证失败")
            return False
            
        # 检查每个预期选中的课程
        for kch, jsh in config.get("selected_courses", {}).items():
            response = requests.post(
                "https://jwxk.shu.edu.cn/xsxk/elective/shu/clazz/list",
                headers={"Authorization": token},
                data={
                    "KCH": kch,
                    "JSH": jsh,
                    "teachingClassType": "XGKC",
                },
                timeout=5
            )
            
            if response.status_code != 200:
                log.error(f"课程 {kch} 状态验证失败")
                return False
                
            try:
                data = response.json()
                rows = data.get("data", {}).get("list", {}).get("rows", [])
                
                course_found = False
                for row in rows:
                    if (row["KCH"] == kch and row["JSH"] == jsh and 
                        row.get("isSelected", False)):
                        course_found = True
                        break
                        
                if not course_found:
                    log.error(f"课程 {kch} 选课状态异常")
                    return False
                    
            except (json.JSONDecodeError, KeyError) as e:
                log.error(f"课程 {kch} 状态解析失败: {e}")
                return False
                
        log.info("所有课程选课状态验证成功")
        return True
        
    except requests.exceptions.RequestException as e:
        log.error(f"选课结果验证网络请求失败: {e}")
        return False


# 添加配置版本检查
def verify_config_version():
    """验证配置文件版本是否兼容"""
    CURRENT_CONFIG_VERSION = "1.0.0"
    config_version = config.get("version", "0.0.0")
    
    try:
        from packaging import version
        if version.parse(config_version) < version.parse(CURRENT_CONFIG_VERSION):
            log.warning(f"配置文件版本 ({config_version}) 低于当前支持的版本 ({CURRENT_CONFIG_VERSION})")
            log.warning("建议更新配置文件以使用新功能")
        return True
    except ImportError:
        log.warning("无法进行版本比较，跳过配置版本检查")
        return True
    except Exception as e:
        log.error(f"配置版本检查失败: {e}")
        return False


# 添加请求限流
class RateLimiter:
    def __init__(self, max_requests=60, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = Lock()
        
    def acquire(self):
        with self.lock:
            now = time.time()
            # 清理过期的请求记录
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time < self.time_window]
            
            if len(self.requests) >= self.max_requests:
                wait_time = self.requests[0] + self.time_window - now
                if wait_time > 0:
                    return wait_time
                    
            self.requests.append(now)
            return 0
            
    def wait(self):
        wait_time = self.acquire()
        if wait_time > 0:
            log.info(f"触发限流，等待 {wait_time:.1f} 秒")
            time.sleep(wait_time)


# 在 main 函数中添加限流器
rate_limiter = RateLimiter()

if __name__ == "__main__":
    main()
