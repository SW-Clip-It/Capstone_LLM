import os
import re
import json
import pandas as pd
from tqdm import tqdm
from datasets import load_dataset
from transformers import RobertaConfig, RobertaModel
from Gutenberg_English_Preprocessor import Gutenberg_English_Preprocessor

# 저장할 최대 책 권수
# 범용적 도메인 어휘사전 구축을 위한 비지도 학습 데이터셋 크기 : 5000
# 토크나이저 자체의 효율성 평가를 위한 테스트 데이터셋 크기 : 28
MAX_BOOKS = 10  
PDNC_INDEXFILE_PATH='/home/urie111/KSCI/TrainTokenizer/Data/project-dialogism-novel-corpus/PDNC-Novel-Index.csv'
PDNC_DATA_FILEPATH='/home/urie111/KSCI/TrainTokenizer/Data/project-dialogism-novel-corpus/data'
SAVE_FILE_PATH="/home/urie111/KSCI/TrainTokenizer/Data/train.jsonl"

# 발화문 추출/ 일반 문장 수 계산
def count_sentences_with_dialogue(text):
    dialogues = re.findall(r'"[^"]*"', text)
    remaining_text = re.sub(r'"[^"]*"', ' ', text)
    sentence_endings = r'(?<=[.!?])(?=\s|[A-Z]|$)'
    other_sentences = re.split(sentence_endings, remaining_text)
    other_sentences_count = len([s for s in other_sentences if s.strip()])
    return round((len(dialogues)/other_sentences_count),2)

# 반복 제거를 위한 PDNC 책 리스트
PDNC_index=pd.read_csv(PDNC_INDEXFILE_PATH)
pdnc_book_title=(PDNC_index['Novel Title'])
print(pdnc_book_title)

pdnc_booktitle_set=set(pdnc_book_title)
print(pdnc_booktitle_set)



# PDNC 데이터의 발화문/일반문장 평균값 구하기
#data 폴더 안의 소설 텍스트의 발화문/일반 문장 모두 구하기
# 발화문/일반 문장의 평균값 구하기
data_list=os.listdir(PDNC_DATA_FILEPATH)
print(data_list)
speech_rate_list=[]

for book in data_list:
    file_path=f'/home/urie111/KSCI/TrainTokenizer/Data/project-dialogism-novel-corpus/data/{book}/novel_text.txt'
    with open(file_path, 'r', encoding='utf-8') as file:
        text = file.read()
        speech_rate=count_sentences_with_dialogue(text)
        speech_rate_list.append(speech_rate)
print(speech_rate_list)

speech_rate_mean=sum(speech_rate_list)/len(speech_rate_list)
print(speech_rate_mean)



datasets = load_dataset(
    "incredible45/Gutenberg-BookCorpus-Cleaned-Data-English",
    split="train",
    streaming=True
)

count = 0

with open(SAVE_FILE_PATH,"w",encoding="utf-8") as f:
    for example in tqdm(datasets, desc="saving books"):
        book_title = example.get("book_title", "untitled")
        
        #PDNC에 저장된 책 이름과 같다면 저장하지 않음.
        if book_title in pdnc_booktitle_set:
            print(f"Skip (Already in PDNC): {book_title}")
            continue

        author= example.get("author", "")
        context = example.get("context", "")

        # context 전처리
        cleaning_processor=Gutenberg_English_Preprocessor(context)
        cleaned_text = cleaning_processor.preprocess()
        context=cleaned_text

        #최소 발화문 비율 충족(작성 필요)
        speech_rate=count_sentences_with_dialogue(context)
        if speech_rate<speech_rate_mean:
            continue

        record={
            "book_title":book_title,
            "author":author,
            "context":context
        }
        f.write(json.dumps(record,ensure_ascii=False)+"\n")
        print("Save_success: ",book_title)

        count +=1

        if count>=MAX_BOOKS:
            break
        

# JSONL 파일 읽기
df = pd.read_json(SAVE_FILE_PATH, lines=True)

# 표 출력 (상위 5개 데이터)
df.head()
