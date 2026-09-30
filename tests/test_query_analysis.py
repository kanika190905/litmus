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


CODEFORCES_WEB = """B. Minus Two
time limit per test2 seconds
memory limit per test256 megabytes
You are given an array a1,a2,...,an. For all indices i, set ai=|ai-2|.
Find the maximum possible frequency of any integer.
Input
The first line contains a single integer t - the number of test cases.
Output
For each test case, output one integer.
Example
InputCopy
2
3
1 3 5
2
4 4
OutputCopy
2
2
Note
In the first test case ...
"""

ATCODER_WEB = """Problem Statement
Given N, print 2N.
Sample Input 1
Copy
3
Sample Output 1
Copy
6

Twice 3 is 6.
Sample Input 2
10
Sample Output 2
20
"""


def test_codeforces_web_copy_paste():
    ex = extract_examples(CODEFORCES_WEB)
    assert [(e.input, e.output) for e in ex] == [("2\n3\n1 3 5\n2\n4 4\n", "2\n2")]
    p = analyze_query(CODEFORCES_WEB)
    assert p.kind == "task_with_examples" and p.platform == "judge-web-copy"


def test_atcoder_web_copy_paste():
    ex = extract_examples(ATCODER_WEB)
    assert [(e.input.strip(), e.output) for e in ex] == [("3", "6"), ("10", "20")]
