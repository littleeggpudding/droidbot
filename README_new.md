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


---

## 下载命令 (rsync)

### Case 1 - com.mkulesh.micromath.plus (server173)
```bash
mkdir -p Downloads/droidbot/test_case_1
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mkulesh.micromath.plus/record_output_Release_v2_20_1_run2 Downloads/droidbot/test_case_1/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mkulesh.micromath.plus/replay_output_Release_v2_23_0_run2_for_Release_v2_20_1 Downloads/droidbot/test_case_1/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mkulesh.micromath.plus/repair_output_Release_v2_23_0_run2_for_Release_v2_20_1 Downloads/droidbot/test_case_1/
```

### Case 2 - com.mirfatif.permissionmanagerx (server173) - dark theme没有点进去
```bash
mkdir -p Downloads/droidbot/test_case_2
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_11_run3 Downloads/droidbot/test_case_2/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_14_PMX_v1_14_run3_for_v1_11 Downloads/droidbot/test_case_2/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_14_PMX_v1_14_run3_for_v1_11 Downloads/droidbot/test_case_2/
```

### Case 3 - com.mirfatif.permissionmanagerx (server173) - dark theme提前结束
```bash
mkdir -p Downloads/droidbot/test_case_3
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_06_run3 Downloads/droidbot/test_case_3/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_26_PMX_v1_26_run3_for_v1_06 Downloads/droidbot/test_case_3/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_26_PMX_v1_26_run3_for_v1_06 Downloads/droidbot/test_case_3/
```

### Case 4 - com.mirfatif.permissionmanagerx (server173) - dark theme在循环
```bash
mkdir -p Downloads/droidbot/test_case_4
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_08_run3 Downloads/droidbot/test_case_4/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_23_PMX_v1_23_run3_for_v1_08 Downloads/droidbot/test_case_4/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_23_PMX_v1_23_run3_for_v1_08 Downloads/droidbot/test_case_4/
```

### Case 5 - com.mirfatif.permissionmanagerx (server173) - mark有问题
```bash
mkdir -p Downloads/droidbot/test_case_5
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_08_run2 Downloads/droidbot/test_case_5/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_17_PMX_v1_17_run2_for_v1_08 Downloads/droidbot/test_case_5/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_17_PMX_v1_17_run2_for_v1_08 Downloads/droidbot/test_case_5/
```

### Case 6 - com.mirfatif.permissionmanagerx (server173) - 判断完成出错
```bash
mkdir -p Downloads/droidbot/test_case_6
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_02_run3 Downloads/droidbot/test_case_6/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_06_run3_for_v1_02 Downloads/droidbot/test_case_6/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_06_run3_for_v1_02 Downloads/droidbot/test_case_6/
```

### Case 7 - com.mirfatif.permissionmanagerx (server173) - 提前结束
```bash
mkdir -p Downloads/droidbot/test_case_7
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/record_output_v1_13_PMX_v1_13_run2 Downloads/droidbot/test_case_7/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/replay_output_v1_29-foss_run2_for_v1_13_PMX_v1_13 Downloads/droidbot/test_case_7/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/com.mirfatif.permissionmanagerx/repair_output_v1_29-foss_run2_for_v1_13_PMX_v1_13 Downloads/droidbot/test_case_7/
```

### Case 8 - com.amaze.filemanager (wenbo) - 需要scroll
```bash
mkdir -p Downloads/droidbot/test_case_8
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_5_1_run2 Downloads/droidbot/test_case_8/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_6_1_run2_for_v3_5_1 Downloads/droidbot/test_case_8/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_6_1_run2_for_v3_5_1 Downloads/droidbot/test_case_8/
```

### Case 9 - com.amaze.filemanager (wenbo)
```bash
mkdir -p Downloads/droidbot/test_case_9
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_5_2_run3 Downloads/droidbot/test_case_9/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_6_7_run3_for_v3_5_2 Downloads/droidbot/test_case_9/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_6_7_run3_for_v3_5_2 Downloads/droidbot/test_case_9/
```

### Case 10 - com.amaze.filemanager (wenbo)
```bash
mkdir -p Downloads/droidbot/test_case_10
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_5_1_run2 Downloads/droidbot/test_case_10/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_10_run2_for_v3_5_1 Downloads/droidbot/test_case_10/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_10_run2_for_v3_5_1 Downloads/droidbot/test_case_10/
```

### Case 11 - com.amaze.filemanager (wenbo)
```bash
mkdir -p Downloads/droidbot/test_case_11
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_5_0_app-play-release-v2_run3 Downloads/droidbot/test_case_11/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_6_6_run3_for_v3_5_0_app-play-release-v2 Downloads/droidbot/test_case_11/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_6_6_run3_for_v3_5_0_app-play-release-v2 Downloads/droidbot/test_case_11/
```

### Case 12 - com.amaze.filemanager (wenbo) - 按钮没标注
```bash
mkdir -p Downloads/droidbot/test_case_12
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_6_1_run2 Downloads/droidbot/test_case_12/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_8_1_run2_for_v3_6_1 Downloads/droidbot/test_case_12/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_8_1_run2_for_v3_6_1 Downloads/droidbot/test_case_12/
```

### Case 13 - com.amaze.filemanager (wenbo)
```bash
mkdir -p Downloads/droidbot/test_case_13
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_7_0_run1 Downloads/droidbot/test_case_13/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_10_run1_for_v3_7_0 Downloads/droidbot/test_case_13/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_10_run1_for_v3_7_0 Downloads/droidbot/test_case_13/
```

### Case 14 - com.amaze.filemanager (wenbo) - 三个点操作选项
```bash
mkdir -p Downloads/droidbot/test_case_14
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_5_1_run3 Downloads/droidbot/test_case_14/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_8_2_run3_for_v3_5_1 Downloads/droidbot/test_case_14/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_8_2_run3_for_v3_5_1 Downloads/droidbot/test_case_14/
```

### Case 15 - com.amaze.filemanager (wenbo) - 点back就成功
```bash
mkdir -p Downloads/droidbot/test_case_15
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_6_0_run2 Downloads/droidbot/test_case_15/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_10_run2_for_v3_6_0 Downloads/droidbot/test_case_15/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_10_run2_for_v3_6_0 Downloads/droidbot/test_case_15/
```

### Case 16 - com.amaze.filemanager (wenbo) - 跟上一个一样
```bash
mkdir -p Downloads/droidbot/test_case_16
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/record_output_v3_6_1_run1 Downloads/droidbot/test_case_16/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/replay_output_v3_6_5_run1_for_v3_6_1 Downloads/droidbot/test_case_16/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.amaze.filemanager/repair_output_v3_6_5_run1_for_v3_6_1 Downloads/droidbot/test_case_16/
```

### Case 17 - com.appmindlab.nano (server97) - 为什么点不开侧边栏
```bash
mkdir -p Downloads/droidbot/test_case_17
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/record_output_v3_9_2_run2 Downloads/droidbot/test_case_17/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/replay_output_v4_5_6_run2_for_v3_9_2 Downloads/droidbot/test_case_17/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/repair_output_v4_5_6_run2_for_v3_9_2 Downloads/droidbot/test_case_17/
```

### Case 18 - com.appmindlab.nano (server97) - 为什么点不开more options
```bash
mkdir -p Downloads/droidbot/test_case_18
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/record_output_v4_0_8_run2 Downloads/droidbot/test_case_18/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/replay_output_v4_5_1_run2_for_v4_0_8 Downloads/droidbot/test_case_18/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.appmindlab.nano/repair_output_v4_5_1_run2_for_v4_0_8 Downloads/droidbot/test_case_18/
```

---

Test cases for improvement method:

Columns:
Repair Events	Failed Events	Repair Result	Note	server	app	Record App	Replay App	Run Count
26	6	Success		wenboo	com.github.anrimian.musicplayer	v0_9_7_1	v0_9_8_2	1
41	36	Success		wenboo	com.github.anrimian.musicplayer	v0_9_7_1	v0_9_8_1	2
100	7	Success		wenboo	com.github.anrimian.musicplayer	v0_9_7	v0_9_8_1	2
7	3	Success		wenboo	com.github.anrimian.musicplayer	v0_9_7_1	v0_9_8_2	2
42	41	Need Check		wenboo	com.github.anrimian.musicplayer	v0_9_7	v0_9_8_2	1

---

com.github.anrimian.musicplayer HTML verification commands (wenbo, 5 cases):

```bash
# Case 1: v0_9_7_1 -> v0_9_8_2, run1
rm -rf /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run1_for_v0_9_7_1
python utils.py -record /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/record_output_v0_9_7_1_run1 -replay /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/replay_output_v0_9_8_2_run1_for_v0_9_7_1 -repair /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run1_for_v0_9_7_1

# Case 2: v0_9_7_1 -> v0_9_8_1, run2
rm -rf /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_1_run2_for_v0_9_7_1
python utils.py -record /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/record_output_v0_9_7_1_run2 -replay /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/replay_output_v0_9_8_1_run2_for_v0_9_7_1 -repair /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_1_run2_for_v0_9_7_1

# Case 3: v0_9_7 -> v0_9_8_1, run2
rm -rf /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_1_run2_for_v0_9_7
python utils.py -record /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/record_output_v0_9_7_run2 -replay /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/replay_output_v0_9_8_1_run2_for_v0_9_7 -repair /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_1_run2_for_v0_9_7

# Case 4: v0_9_7_1 -> v0_9_8_2, run2
rm -rf /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run2_for_v0_9_7_1
python utils.py -record /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/record_output_v0_9_7_1_run2 -replay /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/replay_output_v0_9_8_2_run2_for_v0_9_7_1 -repair /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run2_for_v0_9_7_1

# Case 5: v0_9_7 -> v0_9_8_2, run1
rm -rf /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run1_for_v0_9_7
python utils.py -record /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/record_output_v0_9_7_run1 -replay /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/replay_output_v0_9_8_2_run1_for_v0_9_7 -repair /home2/wenbo/Documents/droidbot/com.github.anrimian.musicplayer/repair_output_v0_9_8_2_run1_for_v0_9_7
```

100	26	Success		wenboo	hu.vmiklos.plees_tracker	v7_4_4	v25_2_1	1
12	10	Success		wenboo	hu.vmiklos.plees_tracker	plees-tracker_24_8_2	plees-tracker_25_8_1	2
100	81	Success		wenboo	hu.vmiklos.plees_tracker	plees-tracker_7_4_2	plees-tracker_7_5_0	2
100	26	Success		wenboo	hu.vmiklos.plees_tracker	plees-tracker_7_5_5	plees-tracker_25_8	1
83	82	Need Check		wenboo	hu.vmiklos.plees_tracker	plees-tracker_7_4_1	v24_2_4	2
100	14	Success		wenboo	hu.vmiklos.plees_tracker	plees-tracker_24_8	plees-tracker_24_8_1	2
21	11	Success		wenboo	hu.vmiklos.plees_tracker	v25_2_1	plees-tracker_25_8_1	2

---

hu.vmiklos.plees_tracker HTML verification commands (wenbo, 7 cases):

```bash
# Case 1: v7_4_4 -> v25_2_1, run1
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_v25_2_1_run1_for_v7_4_4
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_v7_4_4_run1 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_v25_2_1_run1_for_v7_4_4 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_v25_2_1_run1_for_v7_4_4

# Case 2: plees-tracker_24_8_2 -> plees-tracker_25_8_1, run2
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_1_run2_for_plees-tracker_24_8_2
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_plees-tracker_24_8_2_run2 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_plees-tracker_25_8_1_run2_for_plees-tracker_24_8_2 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_1_run2_for_plees-tracker_24_8_2

# Case 3: plees-tracker_7_4_2 -> plees-tracker_7_5_0, run2
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_7_5_0_run2_for_plees-tracker_7_4_2
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_plees-tracker_7_4_2_run2 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_plees-tracker_7_5_0_run2_for_plees-tracker_7_4_2 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_7_5_0_run2_for_plees-tracker_7_4_2

# Case 4: plees-tracker_7_5_5 -> plees-tracker_25_8, run1
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_run1_for_plees-tracker_7_5_5
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_plees-tracker_7_5_5_run1 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_plees-tracker_25_8_run1_for_plees-tracker_7_5_5 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_run1_for_plees-tracker_7_5_5

# Case 5: plees-tracker_7_4_1 -> v24_2_4, run2
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_v24_2_4_run2_for_plees-tracker_7_4_1
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_plees-tracker_7_4_1_run2 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_v24_2_4_run2_for_plees-tracker_7_4_1 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_v24_2_4_run2_for_plees-tracker_7_4_1

# Case 6: plees-tracker_24_8 -> plees-tracker_24_8_1, run2
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_24_8_1_run2_for_plees-tracker_24_8
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_plees-tracker_24_8_run2 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_plees-tracker_24_8_1_run2_for_plees-tracker_24_8 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_24_8_1_run2_for_plees-tracker_24_8

# Case 7: v25_2_1 -> plees-tracker_25_8_1, run2
rm -rf /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_1_run2_for_v25_2_1
python utils.py -record /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/record_output_v25_2_1_run2 -replay /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/replay_output_plees-tracker_25_8_1_run2_for_v25_2_1 -repair /home2/wenbo/Documents/droidbot/hu.vmiklos.plees_tracker/repair_output_plees-tracker_25_8_1_run2_for_v25_2_1
```

7	29	没有生成html		server173	me.hackerchick.catima	2_29_0	2_35_1	1
9	49	没有生成html		server173	me.hackerchick.catima	2_22_1	2_24_2	2
21	38	没有生成html		server173	me.hackerchick.catima	1_4_0	1_14_1	3
23	23	没有生成html		server173	me.hackerchick.catima	2_19_0	2_25_2	3
21	74	没有生成html		server173	me.hackerchick.catima	1_4_0	1_8	3

# me.hackerchick.catima HTML verification commands (server173, 5 cases):


# Case 2: 2_22_1 -> 2_24_2, run2
rm -rf /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_24_2_run2_for_2_22_1
python utils.py -record /data/shiwensong/droidbot/me.hackerchick.catima/record_output_2_22_1_run2 -replay /data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_24_2_run2_for_2_22_1 -repair /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_24_2_run2_for_2_22_1

# Case 3: 1_4_0 -> 1_14_1, run3
rm -rf /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_1_14_1_run3_for_1_4_0
python utils.py -record /data/shiwensong/droidbot/me.hackerchick.catima/record_output_1_4_0_run3 -replay /data/shiwensong/droidbot/me.hackerchick.catima/replay_output_1_14_1_run3_for_1_4_0 -repair /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_1_14_1_run3_for_1_4_0

# Case 4: 2_19_0 -> 2_25_2, run3
rm -rf /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_25_2_run3_for_2_19_0
python utils.py -record /data/shiwensong/droidbot/me.hackerchick.catima/record_output_2_19_0_run3 -replay /data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_25_2_run3_for_2_19_0 -repair /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_25_2_run3_for_2_19_0

# Case 5: 1_4_0 -> 1_8, run3
rm -rf /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_1_8_run3_for_1_4_0
python utils.py -record /data/shiwensong/droidbot/me.hackerchick.catima/record_output_1_4_0_run3 -replay /data/shiwensong/droidbot/me.hackerchick.catima/replay_output_1_8_run3_for_1_4_0 -repair /data/shiwensong/droidbot/me.hackerchick.catima/repair_output_1_8_run3_for_1_4_0

24	20	需要看详情		server97	com.mxt.anitrend	Bump_version_from_1_9_8_to_1_9_9_app-release	v1_11_2_app-release	3


# com.mxt.anitrend HTML verification commands (server97, 1 case):

# Case: Bump_version_from_1_9_8_to_1_9_9_app-release -> v1_11_2_app-release, run3
rm -rf /data/shiwensong/droidbot/com.mxt.anitrend/repair_output_v1_11_2_app-release_run3_for_Bump_version_from_1_9_8_to_1_9_9_app-release
python utils.py -record /data/shiwensong/droidbot/com.mxt.anitrend/record_output_Bump_version_from_1_9_8_to_1_9_9_app-release_run3 -replay /data/shiwensong/droidbot/com.mxt.anitrend/replay_output_v1_11_2_app-release_run3_for_Bump_version_from_1_9_8_to_1_9_9_app-release -repair /data/shiwensong/droidbot/com.mxt.anitrend/repair_output_v1_11_2_app-release_run3_for_Bump_version_from_1_9_8_to_1_9_9_app-release

29	28	需要看详情		server97	me.zhanghai.android.files	v1_3_1	v1_6_2	2
6	5	需要看详情	多点了一步	server97	me.zhanghai.android.files	v1_6_0	v1_7_2	3

# me.zhanghai.android.files HTML verification commands (server97, 2 cases):

# Case 1: v1_3_1 -> v1_6_2, run2
rm -rf /data/shiwensong/droidbot/me.zhanghai.android.files/repair_output_v1_6_2_run2_for_v1_3_1
python utils.py -record /data/shiwensong/droidbot/me.zhanghai.android.files/record_output_v1_3_1_run2 -replay /data/shiwensong/droidbot/me.zhanghai.android.files/replay_output_v1_6_2_run2_for_v1_3_1 -repair /data/shiwensong/droidbot/me.zhanghai.android.files/repair_output_v1_6_2_run2_for_v1_3_1

# Case 2: v1_6_0 -> v1_7_2, run3
rm -rf /data/shiwensong/droidbot/me.zhanghai.android.files/repair_output_v1_7_2_run3_for_v1_6_0
python utils.py -record /data/shiwensong/droidbot/me.zhanghai.android.files/record_output_v1_6_0_run3 -replay /data/shiwensong/droidbot/me.zhanghai.android.files/replay_output_v1_7_2_run3_for_v1_6_0 -repair /data/shiwensong/droidbot/me.zhanghai.android.files/repair_output_v1_7_2_run3_for_v1_6_0



3	3	Failure	为什么点不开侧边栏	server97	com.appmindlab.nano	v3_9_2	v4_5_6	2
36	5	Failure	为什么点不开more options	server97	com.appmindlab.nano	v4_0_8	v4_5_1	2



<!-- 3	3	Not Sure		server97	com.appmindlab.nano	v4_3_2	v4_5_0	3
43	43	Need Check		server97	com.appmindlab.nano	v3_7_8	v4_1_9	1 -->

45	44	not sure		server97	net.bible.android.activity	Release_4_0_629	Release_4_0_653	1
15	13	not sure		server97	net.bible.android.activity	Release_4_0_660	Release_4_0_683	2
15	13	not sure		server97	net.bible.android.activity	Release_5_0_806_andbible-production-806	Release_5_0_832_andbible-production-832	2

-	2	Failure		wenboo	com.activitymanager	5_4_3	5_4_10	3

### Case 19 - com.activitymanager (wenboo) - Failure
mkdir -p Downloads/droidbot/test_case_19
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/record_output_5_4_3_run3 Downloads/droidbot/test_case_19/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/replay_output_5_4_10_run3_for_5_4_3 Downloads/droidbot/test_case_19/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/repair_output_5_4_10_run3_for_5_4_3 Downloads/droidbot/test_case_19/



# check 时跳过 Need_to_delete.csv 中的 case
python check_repair_data.py --apk-base /path/to/data --skip-delete-cases

# repair 时跳过
python start_repair_bash.py --apk-base /path/to/data --skip-delete-cases

# 使用自定义 CSV 路径
python check_repair_data.py --apk-base /path/to/data --skip-delete-cases --delete-csv /path/to/custom.csv


		Failure		wenboo	com.activitymanager	4_1_3	5_4_7	2
		Failure		wenboo	com.activitymanager	4_2_0	5_4_8	2
		Failure		wenboo	com.activitymanager	4_1_0	5_4_15	1
		Failure		wenboo	com.activitymanager	5_3_1	5_4_13	1

### Case 20 - com.activitymanager (wenboo) - record=4_1_3, replay=5_4_7, run=2
```bash
mkdir -p Downloads/droidbot/test_case_20
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/record_output_4_1_3_run2 Downloads/droidbot/test_case_20/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/replay_output_5_4_7_run2_for_4_1_3 Downloads/droidbot/test_case_20/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/repair_output_5_4_7_run2_for_4_1_3 Downloads/droidbot/test_case_20/
```

### Case 21 - com.activitymanager (wenboo) - record=4_2_0, replay=5_4_8, run=2
```bash
mkdir -p Downloads/droidbot/test_case_21
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/record_output_4_2_0_run2 Downloads/droidbot/test_case_21/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/replay_output_5_4_8_run2_for_4_2_0 Downloads/droidbot/test_case_21/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/repair_output_5_4_8_run2_for_4_2_0 Downloads/droidbot/test_case_21/
```

### Case 22 - com.activitymanager (wenboo) - record=4_1_0, replay=5_4_15, run=1
```bash
mkdir -p Downloads/droidbot/test_case_22
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/record_output_4_1_0_run1 Downloads/droidbot/test_case_22/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/replay_output_5_4_15_run1_for_4_1_0 Downloads/droidbot/test_case_22/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/repair_output_5_4_15_run1_for_4_1_0 Downloads/droidbot/test_case_22/
```

### Case 23 - com.activitymanager (wenboo) - record=5_3_1, replay=5_4_13, run=1
```bash
mkdir -p Downloads/droidbot/test_case_23
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/record_output_5_3_1_run1 Downloads/droidbot/test_case_23/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/replay_output_5_4_13_run1_for_5_3_1 Downloads/droidbot/test_case_23/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/com.activitymanager/repair_output_5_4_13_run1_for_5_3_1 Downloads/droidbot/test_case_23/
```

# Jan 6

### Case 24 - me.hackerchick.catima (server173) - Select photos
```bash
mkdir -p Downloads/droidbot/test_case_24
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/record_output_2_16_3_run2 Downloads/droidbot/test_case_24/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_23_2_run2_for_2_16_3 Downloads/droidbot/test_case_24/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_23_2_run2_for_2_16_3 Downloads/droidbot/test_case_24/
```

### Case 25 - me.hackerchick.catima (server173)
```bash
mkdir -p Downloads/droidbot/test_case_25
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/record_output_1_6_1_run1 Downloads/droidbot/test_case_25/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_11_1_run1_for_1_6_1 Downloads/droidbot/test_case_25/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_11_1_run1_for_1_6_1 Downloads/droidbot/test_case_25/
```

### Case 26 - me.hackerchick.catima (server173) - 判断的yes
```bash
mkdir -p Downloads/droidbot/test_case_26
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/record_output_2_17_1_run2 Downloads/droidbot/test_case_26/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_33_0_run2_for_2_17_1 Downloads/droidbot/test_case_26/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_33_0_run2_for_2_17_1 Downloads/droidbot/test_case_26/
```

### Case 27 - me.hackerchick.catima (server173)
```bash
mkdir -p Downloads/droidbot/test_case_27
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/record_output_2_18_2_run3 Downloads/droidbot/test_case_27/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/replay_output_2_25_3_run3_for_2_18_2 Downloads/droidbot/test_case_27/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/me.hackerchick.catima/repair_output_2_25_3_run3_for_2_18_2 Downloads/droidbot/test_case_27/
```

### Case 28 - org.isoron.uhabits (server173)
```bash
mkdir -p Downloads/droidbot/test_case_28
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/record_output_v1_8_9_loop-1_8_9-release_run3 Downloads/droidbot/test_case_28/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/replay_output_v2_1_3_loop-2_1_3-release_run3_for_v1_8_9_loop-1_8_9-release Downloads/droidbot/test_case_28/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/repair_output_v2_1_3_loop-2_1_3-release_run3_for_v1_8_9_loop-1_8_9-release Downloads/droidbot/test_case_28/
```

### Case 29 - org.isoron.uhabits (server173)
```bash
mkdir -p Downloads/droidbot/test_case_29
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/record_output_v1_8_12_loop-1_8_12-release_run2 Downloads/droidbot/test_case_29/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/replay_output_v2_0_2_loop-2_0_2-release_run2_for_v1_8_12_loop-1_8_12-release Downloads/droidbot/test_case_29/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/repair_output_v2_0_2_loop-2_0_2-release_run2_for_v1_8_12_loop-1_8_12-release Downloads/droidbot/test_case_29/
```

### Case 30 - org.isoron.uhabits (server173)
```bash
mkdir -p Downloads/droidbot/test_case_30
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/record_output_v1_8_11_run1 Downloads/droidbot/test_case_30/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/replay_output_v2_0_1_loop-2_0_1-release_run1_for_v1_8_11 Downloads/droidbot/test_case_30/
rsync -avzP shiwensong@10.193.104.173:/data/shiwensong/droidbot/org.isoron.uhabits/repair_output_v2_0_1_loop-2_0_1-release_run1_for_v1_8_11 Downloads/droidbot/test_case_30/
```


Success		server97	com.mxt.anitrend	Bump_version_from_1_8_11_to_1_8_12_app-release	Bump_version_from_1_9_8_to_1_9_9_app-release	3
Success		server97	org.secuso.privacyfriendlynotes	Notes__Privacy_Friendly__v1_2_1	Notes__Privacy_Friendly__v2_0_4	2
Success		server97	eu.faircode.email	1_1964_Ledumahadi	1_2051_Quetecsaurus	2
Success		server140	app.familygem	Family_Gem_0_7_15	Family_Gem_0_9_2	2
Failure	多点了一步	server97	me.zhanghai.android.files	v1_5_0	v1_6_1	2
Failure	多点一步	server97	com.appmindlab.nano	v3_9_2	v4_5_6	2
Success		server97	de.grobox.liberario	Transportr_2_1_4	Transportr_2_2_2	3
Failure	hard case,same page error	server140	code.name.monkey.retromusic	v4_4_0_-_Open_Beta	Release_v5_4_2_-_Open_beta	3
Success		wenbo	org.secuso.privacyfriendlytodolist	ToDo_List__Privacy_Friendly__v2_4_0	ToDo_List__Privacy_Friendly__v3_3_1	2
Failure	多走一步	server173	me.hackerchick.catima	2_25_3	2_26_0	2
Failure	possible events是0	server173	org.isoron.uhabits	v2_0_2_loop-2_0_2-release	v2_2_0_loop-2_2_0-release	2
Failure	没有正确判断功能完成，导致它进入cross page	yiheng	it.feio.android.omninotes	6_2_2	6_2_3	1

---

## New Test Cases (Case 31-39)

### Case 31 - com.mxt.anitrend (server97) - Success
```bash
mkdir -p Downloads/droidbot/test_case_31
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.mxt.anitrend/record_output_Bump_version_from_1_8_11_to_1_8_12_app-release_run3 Downloads/droidbot/test_case_31/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.mxt.anitrend/replay_output_Bump_version_from_1_9_8_to_1_9_9_app-release_run3_for_Bump_version_from_1_8_11_to_1_8_12_app-release Downloads/droidbot/test_case_31/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/com.mxt.anitrend/repair_output_Bump_version_from_1_9_8_to_1_9_9_app-release_run3_for_Bump_version_from_1_8_11_to_1_8_12_app-release Downloads/droidbot/test_case_31/
```

### Case 32 - org.secuso.privacyfriendlynotes (server97) - Success
```bash
mkdir -p Downloads/droidbot/test_case_32
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/org.secuso.privacyfriendlynotes/record_output_Notes__Privacy_Friendly__v1_2_1_run2 Downloads/droidbot/test_case_32/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/org.secuso.privacyfriendlynotes/replay_output_Notes__Privacy_Friendly__v2_0_4_run2_for_Notes__Privacy_Friendly__v1_2_1 Downloads/droidbot/test_case_32/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/org.secuso.privacyfriendlynotes/repair_output_Notes__Privacy_Friendly__v2_0_4_run2_for_Notes__Privacy_Friendly__v1_2_1 Downloads/droidbot/test_case_32/
```

### Case 33 - eu.faircode.email (server97) - Success
```bash
mkdir -p Downloads/droidbot/test_case_33
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/eu.faircode.email/record_output_1_1964_Ledumahadi_run2 Downloads/droidbot/test_case_33/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/eu.faircode.email/replay_output_1_2051_Quetecsaurus_run2_for_1_1964_Ledumahadi Downloads/droidbot/test_case_33/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/eu.faircode.email/repair_output_1_2051_Quetecsaurus_run2_for_1_1964_Ledumahadi Downloads/droidbot/test_case_33/
```

### Case 34 - app.familygem (server140) - Success
```bash
mkdir -p Downloads/droidbot/test_case_34
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/app.familygem/record_output_Family_Gem_0_7_15_run2 Downloads/droidbot/test_case_34/
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/app.familygem/replay_output_Family_Gem_0_9_2_run2_for_Family_Gem_0_7_15 Downloads/droidbot/test_case_34/
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/app.familygem/repair_output_Family_Gem_0_9_2_run2_for_Family_Gem_0_7_15 Downloads/droidbot/test_case_34/
```

### Case 35 - me.zhanghai.android.files (server97) - Failure (多点了一步)
```bash
mkdir -p Downloads/droidbot/test_case_35
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/me.zhanghai.android.files/record_output_v1_5_0_run2 Downloads/droidbot/test_case_35/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/me.zhanghai.android.files/replay_output_v1_6_1_run2_for_v1_5_0 Downloads/droidbot/test_case_35/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/me.zhanghai.android.files/repair_output_v1_6_1_run2_for_v1_5_0 Downloads/droidbot/test_case_35/
```

### Case 36 - de.grobox.liberario (server97) - Success
```bash
mkdir -p Downloads/droidbot/test_case_36
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/de.grobox.liberario/record_output_Transportr_2_1_4_run3 Downloads/droidbot/test_case_36/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/de.grobox.liberario/replay_output_Transportr_2_2_2_run3_for_Transportr_2_1_4 Downloads/droidbot/test_case_36/
rsync -avzP shiwensong@10.193.104.97:/data/a/shiwensong/droidbot/de.grobox.liberario/repair_output_Transportr_2_2_2_run3_for_Transportr_2_1_4 Downloads/droidbot/test_case_36/
```

### Case 37 - code.name.monkey.retromusic (server140) - Failure (hard case)
```bash
mkdir -p Downloads/droidbot/test_case_37
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/code.name.monkey.retromusic/record_output_v4_4_0_-_Open_Beta_run3 Downloads/droidbot/test_case_37/
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/code.name.monkey.retromusic/replay_output_Release_v5_4_2_-_Open_beta_run3_for_v4_4_0_-_Open_Beta Downloads/droidbot/test_case_37/
rsync -avzP shiwensong@10.193.104.140:/data/shiwensong/droidbot/code.name.monkey.retromusic/repair_output_Release_v5_4_2_-_Open_beta_run3_for_v4_4_0_-_Open_Beta Downloads/droidbot/test_case_37/
```

### Case 38 - org.secuso.privacyfriendlytodolist (wenbo) - Success
```bash
mkdir -p Downloads/droidbot/test_case_38
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/org.secuso.privacyfriendlytodolist/record_output_ToDo_List__Privacy_Friendly__v2_4_0_run2 Downloads/droidbot/test_case_38/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/org.secuso.privacyfriendlytodolist/replay_output_ToDo_List__Privacy_Friendly__v3_3_1_run2_for_ToDo_List__Privacy_Friendly__v2_4_0 Downloads/droidbot/test_case_38/
rsync -avzP wenbo@100.85.182.108:/home2/wenbo/Documents/droidbot/org.secuso.privacyfriendlytodolist/repair_output_ToDo_List__Privacy_Friendly__v3_3_1_run2_for_ToDo_List__Privacy_Friendly__v2_4_0 Downloads/droidbot/test_case_38/
```

### Case 39 - it.feio.android.omninotes (yiheng) - Failure
```bash
mkdir -p Downloads/droidbot/test_case_39
rsync -avzP yiheng@10.193.104.97:/data/a/yiheng/droidbot/it.feio.android.omninotes/record_output_6_2_2_run1 Downloads/droidbot/test_case_39/
rsync -avzP yiheng@10.193.104.97:/data/a/yiheng/droidbot/it.feio.android.omninotes/replay_output_6_2_3_run1_for_6_2_2 Downloads/droidbot/test_case_39/
rsync -avzP yiheng@10.193.104.97:/data/a/yiheng/droidbot/it.feio.android.omninotes/repair_output_6_2_3_run1_for_6_2_2 Downloads/droidbot/test_case_39/
```