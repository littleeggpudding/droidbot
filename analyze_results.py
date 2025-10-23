

if __name__ == "__main__":

    #参数
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent_dir", type=str, required=True)
    parser.add_argument("--target", type=str, required=True)
    args = parser.parse_args()

    #1. 调用的一个例子 ./check_output.sh -t replay -p com.byagowi.persiancalendar/
    