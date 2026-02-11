# test

自动化脚本示例：`auto_course.py`

## 功能
- 默认使用 **Edge** 浏览器启动（如果 Edge 不可用会自动回退 Chromium）。
- 打开 `https://mooc.ctt.cn/#/home` 并等待使用者扫码登录。
- 登录后自动进入学习中心：`https://mooc.ctt.cn/#/center/index`
- 自动检索“未完成”课程并进入。
- 自动遍历课程目录，优先学习视频类小节。
- 识别到“测试/测验/练习/作业/考试/答题”等关键词的小节会直接跳过。

## 傻瓜版（一键启动，推荐）
> 只要本机有 Python，就可以直接一键跑。

- Windows：双击 `start.bat`
- Linux / macOS：执行
  ```bash
  ./start.sh
  ```

`start.py` 会自动做三件事：
1. 检测并安装 `playwright`（缺失时自动安装）
2. 安装/校验 `chromium` 浏览器内核
3. 启动 `auto_course.py`

## 手动方式（进阶）
1. 安装依赖：
   ```bash
   pip install playwright
   python -m playwright install chromium
   ```
2. 运行脚本：
   ```bash
   python auto_course.py
   ```
3. 打开浏览器后，在页面扫码登录。

## 说明
- 当前脚本基于页面文本关键词做通用识别，平台 UI 改版后可能需要微调选择器。
- 默认会尝试静音并将视频倍速设置到较高值（浏览器或平台可能限制倍速上限）。
