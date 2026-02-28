
# 定义一个输出字符串的函数
def fun_ctype(s):
    return s.upper()  # 返回字符串的大写形式

# 创建一个列表，用于存储输出结果
output_list = []
num=4
# 使用for循环调用fun_ctype并收集结果
for _ in range(num):
    output_list.append(fun_ctype("Hello, World!"))

# 输出数组的字符串内容
print("Output Array:", output_list)
