# -*- coding: utf-8 -*-
"""Sentiment_Analysis.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1pimhB8vbN6DOyYqxYg5pqKeGqeUq0b0R
"""

import os
import gc
import copy
import time
import random
import string
import joblib

import numpy as np
import pandas as pd

import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler
from torch.utils.data import Dataset, DataLoader

# Utils
from tqdm import tqdm
from collections import defaultdict

from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import GroupKFold, KFold

from transformers import AutoTokenizer, AutoModel, AutoConfig, AdamW
from transformers import DataCollatorWithPadding

from colorama import Fore, Back, Style

b_ = Fore.BLUE
y_ = Fore.YELLOW
sr_ = Style.RESET_ALL

import warnings
warnings.filterwarnings("ignore")

os.environ['CUDA_LAUNCH_BLOCKING'] = "1"

import wandb

try:
    from kaggle_secrets import UserSecretsClient
    user_secrets = UserSecretsClient()
    api_key = user_secrets.get_secret("wandb_api")
    wandb.login(key=api_key)
    anony = None
except:
    anony = "must"
    print('If you want to use your W&B account, go to Add-ons -> Secrets and provide your W&B access token. Use the Label name as wandb_api. \nGet your W&B access token from here: https://wandb.ai/authorize')

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Training Configuration ⚙️ </h3>
</div>
"""

def id_generator(size=12, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))

HASH_NAME = id_generator(size=12)
print(HASH_NAME)

ROOT_PATH = '../input/amazon-review/cleaned_reviews.csv' # Local Machine

CONFIG = {"seed": 2022,
          "epochs": 3,
          "model_name": "microsoft/deberta-v3-base",
          "train_batch_size": 8,
          "valid_batch_size": 16,
          "max_length": 512,
          "learning_rate": 1e-5,
          "scheduler": 'CosineAnnealingLR',
          "min_lr": 1e-6,
          "T_max": 500,
          "weight_decay": 1e-6,
          "n_fold": 3,
          "n_accumulate": 1,
          "num_classes": 3,
          "device": torch.device("cuda:0" if torch.cuda.is_available() else "cpu"),
          "hash_name": HASH_NAME,
          "competition": "amazon-reviews-dataset",
          "_wandb_kernel": "react",
          }

CONFIG["tokenizer"] = AutoTokenizer.from_pretrained(CONFIG['model_name'])
CONFIG['group'] = f'{HASH_NAME}-Baseline'

def set_seeds(config):
    '''Sets the seed of the entire program so results are the same every time we run.
    This is for REPRODUCIBILITY.'''
    seed = config['seed']
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

    os.environ['PYTHONHASHSEED'] = str(seed)

# Usage
set_seeds(CONFIG)

df = pd.read_csv(ROOT_PATH)
df.head()

print('df.shape ', df.shape)
nan_count = df['cleaned_review'].isna().sum()

nan_count

# df['cleaned_review'] = df['cleaned_review'].fillna(' ')
df.dropna(inplace=True)
df.reset_index(drop=True, inplace=True)


print('df.shape ', df.shape)

nan_count_after = df['cleaned_review'].isna().sum()
nan_count_after

df['group'] = df['cleaned_review'].factorize()[0]


# Initialize GroupKFold
gkf = GroupKFold(n_splits=CONFIG['n_fold'])

# Apply group k-fold
for fold, (_, val_index) in enumerate(gkf.split(X=df, groups=df['group'])):
    df.loc[val_index, "kfold"] = int(fold)

df["kfold"] = df["kfold"].astype(int)
df.head()

df.groupby('kfold')['sentiments'].value_counts()

encoder = LabelEncoder()
df['sentiments'] = encoder.fit_transform(df['sentiments'])



with open("le.pkl", "wb") as fp:
    joblib.dump(encoder, fp)

class TextDataset(Dataset):
    def __init__(self, df, tokenizer, max_length):
        self.df = df
        self.max_len = max_length
        self.tokenizer = tokenizer
        self.cleaned_review = df['cleaned_review'].values
        self.targets = df['sentiments'].values

    def __len__(self):
        return len(self.df)


    def __getitem__(self, index):
        cleaned_review = self.cleaned_review[index]
        text = self.tokenizer.sep_token + " " + cleaned_review

        inputs = self.tokenizer.encode_plus(
                        text,
                        truncation=True,
                        add_special_tokens=True,
                        max_length=self.max_len
                    )

        return {
            'input_ids': inputs['input_ids'],
            'attention_mask': inputs['attention_mask'],
            'target': self.targets[index]
        }

collate_fn = DataCollatorWithPadding(tokenizer=CONFIG['tokenizer'])

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Mean Pooling </h3>
</div>
"""

class MeanPooling(nn.Module):
    """ The MeanPooling class inherits from the nn.Module class which is the base class for all neural network modules in PyTorch. """
    def __init__(self):
        super(MeanPooling, self).__init__()
        # In above line __init__() is called to initialize the nn.Module parent class.

    def forward(self, last_hidden_state, attention_mask):


        # First, the attention_mask is expanded to match the size of the last_hidden_state:
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float() # => (batch_size, sequence_length, hidden_size).



        sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, 1)



        sum_mask = input_mask_expanded.sum(1) #=> (batch_size, hidden_size)




        sum_mask = torch.clamp(sum_mask, min=1e-9)

        #Finally, the mean of the embeddings is computed by dividing the sum of the embeddings by the number of actual tokens:
        mean_embeddings = sum_embeddings / sum_mask

        # Result: A 2D tensor of shape (batch_size, hidden_size), representing the sentence-level embeddings computed as the mean of the token-level embeddings (ignoring padding tokens).
        return mean_embeddings

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Create Model </h3>
</div>
"""

class TextModel(nn.Module):
    def __init__(self, model_name):
        super(TextModel, self).__init__()
        self.model = AutoModel.from_pretrained(model_name)
        self.config = AutoConfig.from_pretrained(model_name)
        self.drop = nn.Dropout(p=0.2)
        self.pooler = MeanPooling()
        self.fc = nn.Linear(self.config.hidden_size, CONFIG['num_classes'])

    def forward(self, ids, mask):
        out = self.model(input_ids=ids,attention_mask=mask,
                         output_hidden_states=False)
        out = self.pooler(out.last_hidden_state, mask)
        out = self.drop(out)
        outputs = self.fc(out)
        return outputs

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Loss Function </h3>
</div>
"""

def criterion(outputs, labels):
    return nn.CrossEntropyLoss()(outputs, labels)

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Training Function </h3>
</div>
"""

def train_one_epoch(model, optimizer, scheduler, dataloader, device, epoch):
    model.train()

    dataset_size = 0
    running_loss = 0.0

    bar = tqdm(enumerate(dataloader), total=len(dataloader))
    """ The total argument in tqdm specifies the total number of iterations (or updates to the progress bar). In this case, len(dataloader) is used as the total which is the total number of batches in the dataloader. """
    for step, data in bar:
        ids = data['input_ids'].to(device, dtype = torch.long)
        mask = data['attention_mask'].to(device, dtype = torch.long)
        targets = data['target'].to(device, dtype=torch.long)

        batch_size = ids.size(0)

        outputs = model(ids, mask)

        loss = criterion(outputs, targets)



        loss = loss / CONFIG['n_accumulate']

        loss.backward()

        # After accumulating gradients over the desired number of mini-batches, perform the weight update step.
        if (step + 1) % CONFIG['n_accumulate'] == 0:
            # performs the actual parameter update using the accumulated gradients.
            optimizer.step()

            #  clears out all the accumulated gradients from the parameters to prepare for the next round of accumulation. This happens after every CONFIG['n_accumulate'] batches, as checked by the if condition.
            optimizer.zero_grad()

            if scheduler is not None:
                scheduler.step()

        running_loss += (loss.item() * batch_size)
        dataset_size += batch_size

        epoch_loss = running_loss / dataset_size

        bar.set_postfix(Epoch=epoch, Train_Loss=epoch_loss,
                        LR=optimizer.param_groups[0]['lr'])
    gc.collect()

    return epoch_loss

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Validation Function </h3>
</div>
"""

@torch.no_grad()
def valid_one_epoch(model, dataloader, device, epoch):
    model.eval()

    dataset_size = 0
    running_loss = 0.0

    bar = tqdm(enumerate(dataloader), total=len(dataloader))
    for step, data in bar:
        ids = data['input_ids'].to(device, dtype = torch.long)
        mask = data['attention_mask'].to(device, dtype = torch.long)
        targets = data['target'].to(device, dtype=torch.long)

        batch_size = ids.size(0)

        outputs = model(ids, mask)

        loss = criterion(outputs, targets)

        running_loss += (loss.item() * batch_size)
        dataset_size += batch_size

        epoch_loss = running_loss / dataset_size

        bar.set_postfix(Epoch=epoch, Valid_Loss=epoch_loss,
                        LR=optimizer.param_groups[0]['lr'])

    gc.collect()

    return epoch_loss

"""
<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Run Training </h3>
</div>
"""

def run_training(model, optimizer, scheduler, train_loader, valid_loader, device, num_epochs, fold):

    # To automatically log gradients
    wandb.watch(model, log_freq=100)

    if torch.cuda.is_available():
        print("[INFO] Using GPU: {}\n".format(torch.cuda.get_device_name()))

    start = time.time()

    # Store the initial state of the model
    best_model_wts = copy.deepcopy(model.state_dict())
    best_epoch_loss = np.inf

    # Store the loss for each epoch
    history = defaultdict(list)

    for epoch in range(1, num_epochs + 1):
        gc.collect()
        train_epoch_loss = train_one_epoch(model, optimizer, scheduler,
                                           dataloader=train_loader,
                                           device=CONFIG['device'], epoch=epoch)

        val_epoch_loss = valid_one_epoch(model, valid_loader, device=CONFIG['device'],
                                         epoch=epoch)

        history['Train Loss'].append(train_epoch_loss)
        history['Valid Loss'].append(val_epoch_loss)

        wandb.log({"Train Loss": train_epoch_loss})
        wandb.log({"Valid Loss": val_epoch_loss})

        # If the validation loss improved, save the model weights
        if val_epoch_loss <= best_epoch_loss:
            print(f"{b_}Validation Loss Improved ({best_epoch_loss} ---> {val_epoch_loss})")
            best_epoch_loss = val_epoch_loss
            run.summary["Best Loss"] = best_epoch_loss
            best_model_wts = copy.deepcopy(model.state_dict())
            PATH = f"Loss-Fold-{fold}.bin"
            torch.save(model.state_dict(), PATH)
            # Save a model file from the current directory
            print(f"Model Saved{sr_}")

        print()

    end = time.time()

     # Print total training time and best validation loss
    time_elapsed = end - start
    print('Training complete in {:.0f}h {:.0f}m {:.0f}s'.format(
        time_elapsed // 3600, (time_elapsed % 3600) // 60, (time_elapsed % 3600) % 60))
    print("Best Loss: {:.4f}".format(best_epoch_loss))

    # load best model weights
    model.load_state_dict(best_model_wts)

    return model, history

def get_dataloader(fold):

    df_train = df[df.kfold != fold].reset_index(drop=True)
    df_valid = df[df.kfold == fold].reset_index(drop=True)

    train_dataset = TextDataset(df_train, tokenizer=CONFIG['tokenizer'], max_length=CONFIG['max_length'])
    valid_dataset = TextDataset(df_valid, tokenizer=CONFIG['tokenizer'], max_length=CONFIG['max_length'])

    train_loader = DataLoader(train_dataset, batch_size=CONFIG['train_batch_size'], collate_fn=collate_fn,
                              num_workers=2, shuffle=True, pin_memory=True, drop_last=True)
    valid_loader = DataLoader(valid_dataset, batch_size=CONFIG['valid_batch_size'], collate_fn=collate_fn,
                              num_workers=2, shuffle=False, pin_memory=True)

    return train_loader, valid_loader

from typing import Optional
from torch.optim import Optimizer
from torch.optim.lr_scheduler import (
    _LRScheduler
)

def get_lr_scheduler(optimizer: Optimizer) -> Optional[_LRScheduler]:

    scheduler_type = CONFIG.get('scheduler')

    if scheduler_type == 'CosineAnnealingLR':
        scheduler = lr_scheduler.CosineAnnealingLR(optimizer, T_max=CONFIG.get('T_max'), eta_min=CONFIG.get('min_lr'))

    elif scheduler_type == 'CosineAnnealingWarmRestarts':
        scheduler = lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=CONFIG.get('T_0'), eta_min=CONFIG.get('min_lr'))

    elif scheduler_type is None:
        return None

    else:
        raise ValueError(f"Invalid scheduler specified: {scheduler_type}")

    return scheduler

"""<div style="background: linear-gradient(45deg, #FFC300, #FF5733, #C70039, #900C3F); padding: 10px; border-radius: 5px; display: flex; align-items: center;">
    <h3 style="font-weight: bold; color: white; margin: 0 auto;"> Start Training </h3>
</div>


"""

for fold in range(0, CONFIG['n_fold']):
    print(f"{y_}====== Fold: {fold} ======{sr_}")
    run = wandb.init(project='E_commerce_Review',
                     config=CONFIG,
                     job_type='Train',
                     group=CONFIG['group'],
                     tags=[CONFIG['model_name'], f'{HASH_NAME}'],
                     name=f'{HASH_NAME}-fold-{fold}',
                     anonymous='must')

    train_loader, valid_loader = get_dataloader(fold=fold)

    model = TextModel(CONFIG['model_name'])
    model.to(CONFIG['device'])

    optimizer = AdamW(model.parameters(), lr=CONFIG['learning_rate'], weight_decay=CONFIG['weight_decay'])
    scheduler = get_lr_scheduler(optimizer)

    model, history = run_training(model, optimizer, scheduler, train_loader, valid_loader,
                                  device=CONFIG['device'],
                                  num_epochs=CONFIG['epochs'],
                                  fold=fold, )

    run.finish()

    del model, history, train_loader, valid_loader
    _ = gc.collect()
    print()