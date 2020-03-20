# coding:utf-8
from glob import glob
import os

dst_file = "index_cn.html"
text_list = [
    "余建军：为每个有才能的人提供平台。",
    "他是音频领域的淘宝天猫，在这个平台上。",
    "每个内容生产者都可以很方便地实现自我价值，更多的人拥有微创业的机会。",
    "最近喜马拉雅的曝光率有点高，任性晒出1.7亿元的账户余额的截图。",
    "让业内业外都很惊叹：一个做音频的，居然有这么多钱？",
    "记者查到，网上对喜马拉雅的介绍是。",
    "迅速成长为中国最大的音频分享平台，目前已拥有两亿用户，企业总估值超过三十亿元人民币。",
    "近日，记者在上海章江高科技园区的喜马拉雅基地专访了余建军。",
    "他们都是喊他老余的，不过后来记者问过他的年龄，其实才1977年的。",
    "记者了解到，喜马拉雅采取不多见的联席模式，另一位就是陈晓宇。",
    "两人气质混搭，有点男主外，女主内的意思。",
    "不过他们只是搭档，不是常见的夫妻档模式，用余建军的话来说，这种模式也不常见。",
    "从行业来看 , 服务业受冲击最大 . 数据显示 ，2月份 ，交通运输 , 住宿餐饮 , 旅游 , 居民服务等人员聚集性较强的消费行业需求骤减 , 商务活动指数均落至20%以下 . 不过 , "
    "与抗击疫情相关的医药制造业以及与生活需求相关的农副食品加工 , 食品及酒饮料精制茶等行业PMI回落幅度相对较小 . 得益于云办公 , 在线教育和远程医疗等新业态新技术的支撑 , 电信 , "
    "互联网软件行业PMI明显好于服务业总体水 .平此外 , 2月份 , 金融业PMI为50.1% , 继续保持在扩张区间 , 对疫情防控和经济社会发展发挥了重要作用 . 官方最新披露数据已经传递出制造业复苏的积极信号 . "
    "据统计局数据 , 截至2月25日 , 全国采购经理调查企业中 , 大中型企业复工率为78.9% , 其中大中型制造业企业达到85.6% . "]

text_template = "<br><br><b>(%d) %s</b>"
audio_template = "<div>\n\
    <br>%s倍速度<br>\n\
    <audio controls='controls'>\n\
        <source type='audio/mp3' src='%s'>\n\
        <p>Your browser does not support the audio element.</p>\n\
    </audio>\n\
</div>"

wav_path_list = glob("audios/cn_speech_control_sample/*")
audio_file_list = [os.path.basename(audio_path)
                   for audio_path in glob(os.path.join(wav_path_list[0], "*.wav"))]
print(wav_path_list)

page_file = open("index.html", mode="a", encoding="utf-8")

for index, sentence in enumerate(text_list):
    print(text_template % (index, sentence), file=page_file)
    print("\n", file=page_file)
    for speed_path in wav_path_list:
        speed = speed_path.replace("wavs", "").split("\\")[-1]
        audio_file_path = audio_file_list[index]
        audio_content = audio_template % (speed, os.path.join(speed_path, audio_file_path))
        print(audio_content, file=page_file)
        print("\n", file=page_file)
