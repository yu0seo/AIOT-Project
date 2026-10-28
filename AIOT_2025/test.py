import pandas as pd 
import numpy as np

df = pd.read_csv('./data/2024TrashData.csv')
df['diff'] = df['distance_cm'].diff()
print(df.loc[abs(df['diff']) > 30])

