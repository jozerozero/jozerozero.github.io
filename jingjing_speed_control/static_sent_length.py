# coding=gbk
import re


sent = "它的宽大的叶子也是片片向上，"

preprocess_sent = re.sub("[\s+\.\!\/_，。,$%^*(+\"\']+|[+——！，。？、~@#￥%……&*（）]+", "", sent)

print(preprocess_sent)
print(len(preprocess_sent))
