from litmus.query_analysis import analyze_query, extract_examples

CODEFORCES = """You are given n. Print 2n.

-----Input-----

The only line contains n.

-----Output-----

Print one integer.

-----Examples-----
Input
3

Output
6

Input
10

Output
20

-----Note-----

Easy.
"""

ATCODER = """Given N, print N+1.

-----Sample Input-----
3

-----Sample Output-----
4

Because 3+1=4.
"""

RUSSIAN = """Дано число n.

-----Входные данные-----

В первой строке записано число n.

-----Выходные данные-----

Выведите n.

-----Примеры-----
Входные данные
5

Выходные данные
5
"""


def test_codeforces_examples():
    ex = extract_examples(CODEFORCES)
    assert [(e.input.strip(), e.output) for e in ex] == [("3", "6"), ("10", "20")]


def test_atcoder_output_stops_before_explanation():
    ex = extract_examples(ATCODER)
    assert len(ex) == 1 and ex[0].input == "3\n" and ex[0].output == "4"


def test_russian_format_header_is_not_a_sample():
    ex = extract_examples(RUSSIAN)
    assert [(e.input.strip(), e.output) for e in ex] == [("5", "5")]
    assert analyze_query(RUSSIAN).language == "ru"


def test_categories():
    assert analyze_query(CODEFORCES).kind == "task_with_examples"
    assert analyze_query("How is the input preprocessed before the main function?").kind == "question"
    lc = "Given nums, return the sum.\nExample 1:\nInput: nums = [1,2]\nOutput: 3\n"
    assert analyze_query(lc).kind == "function_task"
