# 1️⃣ 杀掉所有 replay_original.sh 脚本进程
ps -ef | grep 'bash ./replay_original.sh' | grep -v grep | awk '{print $2}' | xargs -r kill -9

# 2️⃣ 杀掉所有正在运行或僵死的 emulator/qemu 实例
adb devices | grep emulator | cut -f1 | xargs -r -I{} adb -s {} emu kill
pkill -f "qemu-system-x86_64-headless" 2>/dev/null || true

# 3️⃣ 清理等待设备的 adb 挂起进程
pgrep -af "adb -s emulator-.* wait-for-device" | awk '{print $1}' | xargs -r kill -9

# 4️⃣ 重启 adb 服务确保环境干净
adb kill-server
adb start-server

# 5️⃣ 检查确认是否都清理掉
ps -ef | grep replay_original.sh | grep -v grep
ps -ef | grep emulator | grep -v grep
adb devices
