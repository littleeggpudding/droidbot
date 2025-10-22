这是一个收集App: org.billthefarmer.diary的例子，其他App就全部替换这个包名就可以

1. Record


python start_bash.py record --csv-file "droidbot/select_apks/org.billthefarmer.diary.csv" --apk-base "droidbot/select_apks/org.billthefarmer.diary" --max-parallel 8 --run-count 3 --parent-dir org.billthefarmer.diary

Check:
./check_output.sh -t record -p org.billthefarmer.diary

有问题的直接删除

2. Replay在原始版本上


python start_bash.py replay_original --csv-file "droidbot/select_apks/org.billthefarmer.diary.csv" --apk-base "droidbot/select_apks/org.billthefarmer.diary" --max-parallel 8 --run-count 3 --parent-dir org.billthefarmer.diary

Check:
./check_output.sh -t replay -p org.billthefarmer.diary

有问题的直接删除

./check_useless_record.sh org.billthefarmer.diary --delete

有问题的直接删除


如果第一步第二步删除的特别多，比如超过10个，重新运行1跟2


3. Replay在新的版本上

python start_bash.py replay_new --csv-file "droidbot/select_apks/org.billthefarmer.diary.csv" --apk-base "droidbot/select_apks/org.billthefarmer.diary" --max-parallel 8 --run-count 3 --parent-dir org.billthefarmer.diary


Check:
./check_output.sh -t replay -p org.billthefarmer.diary

有问题的不用删除，注意不需要删除
