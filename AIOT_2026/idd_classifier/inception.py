"""공식 InceptionTime을 줄인 단일 네트워크. 입력 네 피처는 유지한다."""
import torch
from torch import nn

from .model import check_input


class InceptionModule(nn.Module):
    def __init__(self, inputs, filters, bottleneck, kernels):
        super().__init__()
        self.bottleneck = nn.Conv1d(inputs, bottleneck, 1, bias=False)
        self.branches = nn.ModuleList([nn.Conv1d(bottleneck, filters, kernel, padding=kernel//2, bias=False)
                                       for kernel in kernels])
        self.pool_branch = nn.Sequential(nn.MaxPool1d(3, stride=1, padding=1),
                                         nn.Conv1d(inputs, filters, 1, bias=False))
        self.activation = nn.Sequential(nn.BatchNorm1d(filters*4), nn.ReLU())

    def forward(self, values):
        reduced = self.bottleneck(values)
        branches = [conv(reduced) for conv in self.branches]
        return self.activation(torch.cat([*branches, self.pool_branch(values)], dim=1))


class InceptionResidualBlock(nn.Module):
    def __init__(self, inputs, filters, bottleneck, kernels):
        super().__init__()
        channels = filters*4
        self.modules_path = nn.Sequential(InceptionModule(inputs, filters, bottleneck, kernels),
                                           InceptionModule(channels, filters, bottleneck, kernels),
                                           InceptionModule(channels, filters, bottleneck, kernels))
        self.shortcut = nn.Sequential(nn.Conv1d(inputs, channels, 1, bias=False), nn.BatchNorm1d(channels))

    def forward(self, values):
        return torch.relu(self.modules_path(values)+self.shortcut(values))


class SmallInceptionTime(nn.Module):
    def __init__(self, filters=16, bottleneck=16, depth=3, kernels=(39, 19, 9), dropout=.3):
        super().__init__()
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in (filters, bottleneck, depth)) or depth % 3:
            raise ValueError('필터/bottleneck은 양의 정수, 깊이는 양의 3의 배수여야 합니다.')
        if len(kernels) != 3 or any(not isinstance(k, int) or k < 1 or k % 2 == 0 for k in kernels):
            raise ValueError('서로 다른 시간 범위를 위한 홀수 커널 3개가 필요합니다.')
        if not 0 <= dropout < 1:
            raise ValueError('dropout은 0 이상 1 미만이어야 합니다.')
        self.encoder = nn.Sequential(*[InceptionResidualBlock(4 if index == 0 else filters*4,
                                                              filters, bottleneck, kernels)
                                       for index in range(depth//3)])
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(filters*4, 1)

    def forward(self, features):
        check_input(features)
        encoded = self.encoder(features.transpose(1, 2))
        return self.classifier(self.dropout(encoded.mean(dim=2))).squeeze(-1)
