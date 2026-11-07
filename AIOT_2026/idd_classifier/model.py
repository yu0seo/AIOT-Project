"""동일한 네 피처를 받는 LSTM/GRU와 인과적 TCN. 출력은 이진 logit이다."""
import torch
from torch import nn


def check_input(features):
    if features.ndim != 3 or features.shape[-1] != 4:
        raise ValueError("입력은 (batch, time, 4)여야 합니다.")


def pool_sequence(sequence, pooling):
    if pooling == "last":
        return sequence[:, -1]
    if pooling == "statistics":
        return torch.cat([sequence[:, -1], sequence.mean(dim=1), sequence.amax(dim=1),
                          sequence.std(dim=1, unbiased=False)], dim=1)
    raise ValueError(f"지원하지 않는 시점 요약 방식: {pooling}")


def pooled_size(hidden_size, pooling):
    if pooling not in ("last", "statistics"):
        raise ValueError(f"지원하지 않는 시점 요약 방식: {pooling}")
    return hidden_size*(4 if pooling == "statistics" else 1)


class DrivingLSTM(nn.Module):
    def __init__(self, hidden_size=32, num_layers=1, dropout=.3, pooling="last"):
        super().__init__()
        # PyTorch의 LSTM dropout은 여러 층 사이에서만 적용된다. 단층도 head dropout을 쓴다.
        self.lstm = nn.LSTM(input_size=4, hidden_size=hidden_size, num_layers=num_layers,
                            batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.dropout = nn.Dropout(dropout)
        self.pooling = pooling
        self.classifier = nn.Linear(pooled_size(hidden_size, pooling), 1)

    def forward(self, features):
        check_input(features)
        sequence, _ = self.lstm(features)
        return self.classifier(self.dropout(pool_sequence(sequence, self.pooling))).squeeze(-1)


class DrivingGRU(nn.Module):
    def __init__(self, hidden_size=32, num_layers=1, dropout=.1, pooling="statistics"):
        super().__init__()
        self.gru = nn.GRU(4, hidden_size, num_layers, batch_first=True,
                          dropout=dropout if num_layers > 1 else 0)
        self.pooling = pooling
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(pooled_size(hidden_size, pooling), 1)

    def forward(self, features):
        check_input(features)
        sequence, _ = self.gru(features)
        return self.classifier(self.dropout(pool_sequence(sequence, self.pooling))).squeeze(-1)


class CausalBlock(nn.Module):
    def __init__(self, inputs, channels, dilation, dropout):
        super().__init__()
        self.left_padding = 4*dilation
        self.conv = nn.Conv1d(inputs, channels, kernel_size=5, dilation=dilation)
        self.skip = nn.Conv1d(inputs, channels, 1) if inputs != channels else nn.Identity()
        self.dropout = nn.Dropout(dropout)

    def forward(self, values):
        padded = nn.functional.pad(values, (self.left_padding, 0))
        return self.skip(values)+self.dropout(nn.functional.gelu(self.conv(padded)))


class DrivingTCN(nn.Module):
    def __init__(self, hidden_size=32, num_layers=4, dropout=.1, pooling="statistics"):
        super().__init__()
        self.encoder = nn.Sequential(*[CausalBlock(4 if layer == 0 else hidden_size, hidden_size,
                                                  2**layer, dropout) for layer in range(num_layers)])
        self.pooling = pooling
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(pooled_size(hidden_size, pooling), 1)

    def forward(self, features):
        check_input(features)
        sequence = self.encoder(features.transpose(1, 2)).transpose(1, 2)
        return self.classifier(self.dropout(pool_sequence(sequence, self.pooling))).squeeze(-1)


def create_model(model_type, architecture):
    """번들의 명시적인 모델 종류만 허용한다. 이전 LSTM 번들도 그대로 읽는다."""
    models = {"LSTM": DrivingLSTM, "GRU": DrivingGRU, "TCN": DrivingTCN}
    if model_type not in models:
        raise ValueError(f"지원하지 않는 모델 종류: {model_type}")
    return models[model_type](**architecture)


def model_architecture(config):
    return {key: config[key] for key in ("hidden_size", "num_layers", "dropout", "pooling") if key in config}


@torch.inference_mode()
def predict_scores(model, features, batch_size=256, device="cpu"):
    model.eval()
    result = []
    for start in range(0, len(features), batch_size):
        batch = torch.as_tensor(features[start:start+batch_size], dtype=torch.float32, device=device)
        result.append(torch.sigmoid(model(batch)).cpu())
    return torch.cat(result).numpy()
