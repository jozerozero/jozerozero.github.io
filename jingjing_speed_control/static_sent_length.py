# coding=gbk
import re


sent = "���Ŀ���Ҷ��Ҳ��ƬƬ���ϣ�"

preprocess_sent = re.sub("[\s+\.\!\/_����,$%^*(+\"\']+|[+��������������~@#��%����&*����]+", "", sent)

print(preprocess_sent)
print(len(preprocess_sent))
