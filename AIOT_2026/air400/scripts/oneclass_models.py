"""Two-input 30-second models: reconstruction autoencoder and Deep SVDD encoder."""
import torch
from torch import nn


class FusionEncoder(nn.Module):
    """Same bias-free encoder in both experiments; final representation is linear."""
    def __init__(self):
        super().__init__()
        self.wave_encoder = nn.Sequential(
            nn.Conv1d(1, 16, 7, stride=2, padding=3, bias=False), nn.ReLU(),
            nn.Conv1d(16, 32, 5, stride=2, padding=2, bias=False), nn.ReLU(),
            nn.Conv1d(32, 32, 5, stride=3, padding=2, bias=False), nn.ReLU(),
            nn.Flatten(), nn.Linear(32*25, 32, bias=False), nn.ReLU(),
        )
        self.feature_encoder = nn.Sequential(
            nn.Linear(9, 16, bias=False), nn.ReLU(),
            nn.Linear(16, 8, bias=False), nn.ReLU(),
        )
        self.fusion = nn.Linear(40, 16, bias=False)

    def forward(self, waveform, features):
        w = self.wave_encoder(waveform.transpose(1, 2))
        f = self.feature_encoder(features)
        return self.fusion(torch.cat([w, f], dim=1))


class FusionAutoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = FusionEncoder()
        self.wave_decoder = nn.Sequential(
            nn.Linear(16, 25*32), nn.ReLU(), nn.Unflatten(1, (32, 25)),
            nn.Upsample(scale_factor=3, mode="nearest"),
            nn.Conv1d(32, 32, 5, padding=2), nn.ReLU(),
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv1d(32, 16, 5, padding=2), nn.ReLU(),
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv1d(16, 1, 7, padding=3),
        )
        self.feature_decoder = nn.Sequential(nn.Linear(16, 16), nn.ReLU(), nn.Linear(16, 9))

    def forward(self, waveform, features):
        z = self.encoder(waveform, features)
        return self.wave_decoder(z).transpose(1, 2), self.feature_decoder(z), z


def reconstruction_scores(predicted_wave, predicted_features, wave, features):
    wave_error = (predicted_wave-wave).abs().mean(dim=(1, 2))
    feature_error = (predicted_features-features).abs().mean(dim=1)
    return wave_error+feature_error, wave_error, feature_error


def svdd_scores(representations, center):
    return (representations-center).square().sum(dim=1)
