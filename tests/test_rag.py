from paper_agent.rag import bm25_scores, tokenize


def test_bm25_ranks_relevant_document_first():
    documents = [
        "retrieval augmented generation for open domain question answering",
        "image classification with convolutional neural networks",
        "a study of protein folding dynamics",
    ]
    scores = bm25_scores("retrieval augmented generation", documents)
    assert scores[0] == max(scores)
    assert scores[0] > scores[1]


def test_tokenize_handles_chinese():
    tokens = tokenize("检索增强生成")
    assert "检" in tokens       # 单字
    assert "检索" in tokens     # 二元组
