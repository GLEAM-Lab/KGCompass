import traceback
from transformers import AutoModel
import numpy as np

class Embedding:
    _instance = None
    _model = None
    
    def __new__(cls):
        if cls._instance is None:
            print("创建新的 Embedding 实例")
            cls._instance = super().__new__(cls)
            
            try:
                print("初始化 pipeline...")
                cls._model = AutoModel.from_pretrained("jinaai/jina-embeddings-v2-base-code", trust_remote_code=True).to("cuda:0")
                print("embedding model 初始化成功")
            except Exception as e:
                print(f"pipeline 初始化失败: {e}")
                raise
        return cls._instance
    
    def __init__(self):
        pass
    
    def get_embedding(self, text):
        """获取文本的 embedding"""
        try:
            if text is None:
                print("警告: 输入文本为 None")
                return None
                
            if not isinstance(text, str):
                print(f"警告: 输入文本类型不是字符串，而是 {type(text)}")
                text = str(text)
                
            if not text.strip():
                print("警告: 输入文本为空")
                return None
            
            return self._model.encode([text])[0].tolist()
            
        except Exception as e:
            print(f"获取 embedding 时出错: {e}")
            print(f"model 状态: {self._model}")
            print(traceback.format_exc())
            return None

    def _cos_similarity(self, vec1, vec2):
        """计算两个向量的余弦相似度"""
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    def text_similarity(self, text1, text2):
        """计算两个文本的相似度"""
        vec1 = self.get_embedding(text1)
        vec2 = self.get_embedding(text2)
        return self._cos_similarity(vec1, vec2)
