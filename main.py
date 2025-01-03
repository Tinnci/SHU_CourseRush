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
from threading import Lock
import logging.config
import os
import sys
import shutil
import signal

def setup_logging():
    """配置日志"""
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s - %(levelname)s - %(message)s'
            },
        },
        'handlers': {
            'file': {
                'level': 'DEBUG',
                'class': 'logging.FileHandler',
                'filename': 'app.log',
                'formatter': 'standard',
                'encoding': 'utf-8',
            },
            'console': {
                'level': 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
            },
        },
        'loggers': {
            '': {  # root logger
                'handlers': ['console', 'file'],
                'level': 'DEBUG',
                'propagate': True
            }
        }
    }
    logging.config.dictConfig(logging_config)

def validate_config(config):
    """验证配置文件"""
    required_fields = ['username', 'password', 'browser']
    for field in required_fields:
        if not config.get(field):
            raise ValueError(f"配置错误: {field} 不能为空")
    
    if not config.get("courses"):
        raise ValueError("配置错误: 未设置任何课程")
    
    for course in config.get("courses", []):
        if not course.get("KCH"):
            raise ValueError("配置错误: 课程号(KCH)不能为空")
        if not course.get("JSH"):
            raise ValueError("配置错误: 教师号(JSH)不能为空")

def load_config(file_path="config.toml"):
    """加载并验证配置"""
    try:
        if not os.path.exists(file_path):
            template_path = "config.template.toml"
            if os.path.exists(template_path):
                shutil.copy(template_path, file_path)
                log.info(f"已创建配置文件模板: {file_path}")
                log.info("请编辑配置文件并重新运行程序")
                sys.exit(0)
            else:
                raise FileNotFoundError(f"配置文件不存在: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            config = toml.load(f)
            
        validate_config(config)
        return config
    except Exception as e:
        log.error(f"加载配置文件失败: {e}")
        sys.exit(1)

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

class TokenManager:
    def __init__(self, cache_duration=1800):
        self._token = None
        self._valid_until = 0
        self._cache_duration = cache_duration
        self._lock = Lock()

    def get_token(self, force_refresh=False):
        """获取token的公共方法"""
        with self._lock:
            now = time.time()
            
            # 如果token仍然有效且不强制刷新，直接返回
            if not force_refresh and self._token and now < self._valid_until:
                return self._token

            # 尝试获取新token
            try:
                if self._get_new_token():
                    self._valid_until = now + self._cache_duration
                    return self._token
                return None
            except Exception as e:
                log.error(f"获取token失败: {e}")
                return None

    def _get_new_token(self):
        """获取新token的私有方法"""
        driver = None
        try:
            browser_type = config.get("browser").lower()
            
            if browser_type == "chrome":
                chrome_options = ChromeOptions()
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('--headless')
                chrome_options.add_argument('--disable-extensions')
                driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
            elif browser_type == "firefox":
                firefox_options = FirefoxOptions()
                driver = webdriver.Firefox(service=FirefoxService(), options=firefox_options)
            elif browser_type == "edge":
                edge_options = EdgeOptions()
                driver = webdriver.Edge(service=EdgeService(), options=edge_options)
            else:
                raise ValueError(f"不支持的浏览器类型: {browser_type}")

            log.info("正在访问登录页面...")
            driver.get("https://jwxk.shu.edu.cn/")
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            driver.find_element(By.ID, "username").send_keys(config.get("username"))
            driver.find_element(By.ID, "password").send_keys(config.get("password"))
            
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit-button"))
            )
            time.sleep(1)
            submit_button.click()
            time.sleep(2)
            log.info("登录成功，等待选择学期冷却...")
            time.sleep(10)
            
            try:
                confirm_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(@class, 'el-button--primary') and .//span[text()='确 定']]")
                    )
                )
                confirm_button.click()
                log.info("点击确定按钮成功")
            except (TimeoutException, NoSuchElementException) as e:
                log.error(f"未能找到或点击确定按钮: {e}")

            cookies = driver.get_cookies()
            for cookie in cookies:
                if cookie["name"] == "Authorization":
                    self._token = cookie["value"]
                    log.info(f"获取到的 Token: {self._token}")
                    break

            if not self._token:
                raise Exception("未找到Authorization cookie")

            return self._verify_token()

        except Exception as e:
            log.error(f"获取token过程中出错: {e}")
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    log.warning(f"关闭浏览器时出错: {e}")

    def _verify_token(self):
        """验证token是否有效"""
        if not self._token:
            return False
            
        try:
            response = requests.get(
                "https://jwxk.shu.edu.cn/test",
                headers={"Authorization": self._token},
                timeout=5
            )
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            log.warning(f"Token验证请求失败: {e}")
            return False

# 创建全局 TokenManager 实例
token_manager = TokenManager()

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
    """查询并添加课程"""
    headers = {
        "Authorization": token_manager.get_token(),
        "User-Agent": random.choice(user_agents),
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        # 修改这里：使用 teachingClassType 而不是 clazzType
        list_data = {
            "teachingClassType": "XGKC",  # 改回原来的参数名
            "pageNumber": "1",
            "pageSize": "10",
            "KCH": course["KCH"],
            "JSH": course["JSH"]
        }

        log.info(f"正在查询课程 {course['KCH']} (优先级: {course.get('priority', 999)})")
        
        # 添加请求数据调试
        log.debug(f"请求数据: {list_data}")
        
        response = requests.post(
            list_url,
            headers=headers,
            data=list_data,
            timeout=10
        )
        
        log.debug(f"查询响应状态码: {response.status_code}")
        log.debug(f"响应内容: {response.text}")  # 添加完整响应内容调试
        
        response.raise_for_status()

        try:
            response_data = response.json()
            log.debug(f"解析后的JSON数据: {response_data}")  # 添加这行来查看解析后的数据
            
            if not response_data:
                log.warning("响应数据为空")
                return False
                
            # 检查响应中是否包含错误信息
            if response_data.get("code") != 200:
                log.warning(f"API返回错误: {response_data.get('msg', '未知错误')}")
                if response_data.get("code") == 401:
                    log.warning("Token 失效，正在更新 Token...")
                    token_manager.get_token(force_refresh=True)
                return False
                
            # 获取数据部分
            data = response_data.get("data")
            if not data:
                log.warning(f"响应中无data字段: {response_data}")
                return False
                
            # 获取列表数据
            list_data = data.get("list")
            if not list_data:
                log.warning(f"data中无list字段: {data}")
                return False
                
            # 获取行数据
            rows = list_data.get("rows", [])
            if not rows:
                log.info(f"未找到课程 {course['KCH']} 的信息")
                return False
                
            for row in rows:
                current_selected = row.get("numberOfSelected", 0)
                capacity = row.get("classCapacity", 0)
                log.info(f"课程 {course['KCH']} 当前已选 {current_selected}/{capacity}")
                
                if current_selected < capacity or config.get("allow_over_capacity", False):
                    add_data = {
                        "clazzId": row["JXBID"],
                        "secretVal": row["secretVal"],
                        "clazzType": "XGKC"
                    }
                    
                    add_response = requests.post(
                        add_url,
                        headers=headers,
                        data=add_data,
                        timeout=10
                    )
                    
                    # 添加选课响应调试
                    try:
                        add_response_text = add_response.text
                        log.debug(f"选课响应内容: {add_response_text}")
                    except Exception as e:
                        log.warning(f"无法读取选课响应内容: {e}")
                    
                    if add_response.status_code == 200:
                        try:
                            add_result = add_response.json()
                            if add_result.get("code") == 200:
                                log.info(f"课程 {course['KCH']} 添加成功!")
                                return True
                            else:
                                log.warning(f"添加课程失败: {add_result.get('msg', '未知错误')}")
                        except json.JSONDecodeError:
                            log.warning("无法解析选课响应")
                    else:
                        log.warning(f"课程 {course['KCH']} 添加失败，状态码: {add_response.status_code}")
                        if add_response.status_code == 401:
                            log.warning("Token 失效，正在更新 Token...")
                            token_manager.get_token(force_refresh=True)
                else:
                    log.info(f"课程 {course['KCH']} 已满，继续尝试...")
                    
        except json.JSONDecodeError as e:
            log.error(f"JSON 解析失败: {e}")
            log.error(f"响应内容: {response.text}")
            if response.status_code == 401:
                log.warning("Token可能失效，尝试刷新...")
                token_manager.get_token(force_refresh=True)
            return False
            
    except requests.exceptions.RequestException as e:
        log.error(f"查询或添加课程失败: {e}")
        return False
        
    return False

def query_courses_multithread():
    """多线程查询课程"""
    # 按优先级排序课程
    sorted_courses = sorted(
        config.get("courses", []),
        key=lambda x: x.get("priority", 999)
    )
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(query_and_add_course, course) 
                  for course in sorted_courses]
        for future in as_completed(futures):
            if future.result():
                return True
    return False

def query_courses_singlethread():
    """单线程查询课程"""
    # 按优先级排序课程
    sorted_courses = sorted(
        config.get("courses", []),
        key=lambda x: x.get("priority", 999)
    )
    
    for course in sorted_courses:
        if query_and_add_course(course):
            return True
    return False

def signal_handler(signum, frame):
    """处理退出信号"""
    log.info("接收到退出信号，正在清理...")
    # 在这里添加清理代码
    sys.exit(0)

def main():
    """主函数"""
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    setup_logging()
    log.info("程序启动")
    if not token_manager.get_token():
        log.error("无法获取有效token")
        return
        
    attempt = 0
    while True:
        attempt += 1
        log.info(f"第 {attempt} 次尝试...")

        # 检查token是否需要更新
        if not token_manager.get_token():
            log.error("Token已失效且无法更新")
            return

        success = (
            query_courses_multithread()
            if config.get("use_multithreading", False)
            else query_courses_singlethread()
        )

        if success:
            log.info(f"抢课成功! 第 {attempt} 次尝试")
            break

        # 添加随机波动的等待时间
        wait_time = config.get("wait_time", 5.0)
        fluctuated_wait_time = max(0, wait_time + random.uniform(-0.2, 0.2))
        log.info(f"等待时间: {fluctuated_wait_time:.2f} 秒")
        time.sleep(fluctuated_wait_time)

if __name__ == "__main__":
    main()
