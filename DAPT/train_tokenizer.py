'''
파일명: train_tokenizer.py
목적: distilroberta-base 토크나이저의 어휘 사전 확장
      고전 영문학 도메인 코퍼스(JSONL)에서 신규 토큰을 추출하여 기존 사전에 추가

처리 순서:
    1. distilroberta-base 토크나이저 로드
    2. 도메인 코퍼스(JSONL)에서 context 필드 추출 후 BPE 토크나이저 학습
    3. 도메인 vocab에서 기존 vocab에 없는 신규 토큰 필터링
    4. 기존 토크나이저에 신규 토큰 추가 후 저장
    5. 확장 전후 토크나이저 검증 결과 JSONL로 기록

입력:
    - TRAINING_DATA_PATH : 도메인 코퍼스 JSONL 파일 (각 줄: {"context": "..."})
    
출력:
    - EXTENDED_TOKENIZER : 사전 확장된 토크나이저 저장 경로
    - OUTPUT_ARCHIVE     : 확장 전후 검증 결과 JSONL 파일
'''

from tokenizers import ByteLevelBPETokenizer
from transformers import RobertaTokenizer
import json
from pathlib import Path
from collections import OrderedDict

TRAINING_DATA_PATH="/home/urie111/KSCI/TrainTokenizer/Data/train.jsonl"
EXTENDED_TOKENIZER="/home/urie111/KSCI/TrainTokenizer/tokenizer/extended_tokenizer"
OUTPUT_ARCHIVE="/home/urie111/KSCI/TrainTokenizer/output_train.jsonl"

# JSONL 파일에서 'context'만 추출하여 배치 단위로 전달하는 제너레이터
def novel_batch_iterator(file_path, batch_size=100):
    with open(file_path, 'r', encoding='utf-8') as f:
         batch=[]
         for line in f:
            record=json.loads(line)
            batch.append(record.get("context",""))
            
            if len(batch)==batch_size:
                yield batch
                batch=[]
         if batch:
            yield batch
            
# 토크나이저 학습 코드
model_name = "distilroberta-base"
extention_tokenizer = RobertaTokenizer.from_pretrained(model_name)

domain_tokenizer = ByteLevelBPETokenizer()
domain_tokenizer.train_from_iterator(
    iterator=novel_batch_iterator(TRAINING_DATA_PATH),
    vocab_size=30000,              # 설정 issue 
    min_frequency=20,               # 해당 토큰이 최소 몇 번 등장해야 vocab에 포함시킬지에 대한 . 
    special_tokens=["<s>", "<pad>", "</s>", "<unk>", "<mask>"] #distilroberta와 일치함
    )

existing_vocab = set(extention_tokenizer.get_vocab().keys())
domain_vocab = domain_tokenizer.get_vocab()  # {token: id} 형태 

new_tokens = [
    token for token in domain_vocab.keys() # token(토큰 문자열)을 비교
    if token not in existing_vocab
]

num_added = extention_tokenizer.add_tokens(new_tokens)
extention_tokenizer.save_pretrained(EXTENDED_TOKENIZER)

model_name = "distilroberta-base"
original_tokenizer = RobertaTokenizer.from_pretrained(model_name)
# 기존 토크나이저 : 검증 결과
test_texts = [
    "thou shalt not covet",
    "hath not a Jew eyes",
    "wherefore art thou Romeo",
]

original_validation_results = []
for text in test_texts:
    tokens = original_tokenizer.tokenize(text)
    original_validation_results.append({
        "input": text,
        "original": {
            "input": text,
            "tokens": tokens,                      # ✅
            "token_count": len(tokens)             # ✅
        },
    })
    
# 기존 토크나이저 : 결과 기록
# 기존 토크나이저 결과 기록
output_original = OrderedDict()
output_original["type"] = "original"
output_original["original_vocab_size"] = len(existing_vocab)
output_original["new_token_candidates"] = 0
output_original["added_token_count"] = 0
output_original["vocab_size"] = len(existing_vocab)
output_original["added_token_sample"] = []
output_original["validation"] = original_validation_results

# 사전 확장 토크나이저: 검증 결과
extention_validation_results = []
for text in test_texts:
    tokens = extention_tokenizer.tokenize(text)
    extention_validation_results.append({
        "input": text,
        "tokens": tokens,
        "token_count": len(tokens)
    })
    
# 사전확장 토크나이저: 실행 결과 기록하기 
output_extended = OrderedDict()
output_extended["type"] = "extended"
output_extended["original_vocab_size"] = len(existing_vocab)
output_extended["new_token_candidates"] = len(domain_vocab)
output_extended["new_token_count"] = len(new_tokens)
output_extended["added_token_count"] = num_added
output_extended["vocab_size"] = len(existing_vocab) + num_added
output_extended["added_token_sample"] = new_tokens[:10]
output_extended["validation"] = extention_validation_results

with open(OUTPUT_ARCHIVE, "w", encoding="utf-8") as f:
    f.write(json.dumps(output_original, ensure_ascii=False) + "\n")
    f.write(json.dumps(output_extended, ensure_ascii=False) + "\n")