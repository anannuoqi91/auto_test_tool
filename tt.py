import time
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from set_simpl import *
change_channel(channel_type="cluster",
               user_name="operator", password="operator")

options = Options()
print("11111111111111111")
driver = webdriver.Chrome(options=options)
print("11111111111111111")
driver.get("http://localhost/#/traffic")
time.sleep(2)   # 等页面先加载完
print("11111111111111111")
driver.refresh()  # 刷新页面
print("11111111111111111")
time.sleep(5)
driver.quit()
print("11111111111111111")
