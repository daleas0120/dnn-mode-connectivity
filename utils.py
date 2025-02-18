import numpy as np
import os
import torch
import torch.nn.functional as F

import curves

if torch.cuda.is_available():
    device = 'cuda'
else:
    device = 'cpu'


def l2_regularizer(weight_decay):
    def regularizer(model):
        l2 = 0.0
        for p in model.parameters():
            l2 += torch.sqrt(torch.sum(p ** 2))
        return 0.5 * weight_decay * l2
    return regularizer


def cyclic_learning_rate(epoch, cycle, alpha_1, alpha_2):
    def schedule(i):
        t = ((epoch % cycle) + i) / cycle
        if t < 0.5:
            return alpha_1 * (1.0 - 2.0 * t) + alpha_2 * 2.0 * t
        else:
            return alpha_1 * (2.0 * t - 1.0) + alpha_2 * (2.0 - 2.0 * t)
    return schedule


def adjust_learning_rate(optimizer, lr):
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
    return lr


def save_checkpoint(dir, epoch, name='checkpoint', **kwargs):
    state = {
        'epoch': epoch,
    }
    state.update(kwargs)
    filepath = os.path.join(dir, '%s-%d.pt' % (name, epoch))
    torch.save(state, filepath)


def train(train_loader, model, optimizer, criterion, regularizer=None, lr_schedule=None):
    loss_sum = 0.0
    correct = 0.0

    num_iters = len(train_loader)
    model.train()
    for i, (sample_input, target) in enumerate(train_loader):
        if lr_schedule is not None:
            lr = lr_schedule(i / num_iters)
            adjust_learning_rate(optimizer, lr)
        # sample_input = sample_input.cuda(async=True)
        # target = target.cuda(async=True)
        
        device = next(model.parameters()).device
        print(device)

        sample_input.to(device)
        target.to(device)

        print(sample_input.dtype)
        print(target.dtype)

        optimizer.zero_grad()
        output = model(sample_input)
        
        loss = criterion(output, target)
        if regularizer is not None:
            loss += regularizer(model)

        # optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        loss_sum += loss.item() * sample_input.size(0)
        pred = output.data.argmax(1, keepdim=True)
        correct += pred.eq(target.data.view_as(pred)).sum().item()

    return {
        'loss': loss_sum / len(train_loader.dataset),
        'accuracy': correct * 100.0 / len(train_loader.dataset),
    }


def new_train(train_loader, model, optimizer, criterion, regularizer=None, lr_schedule=None):
    loss_sum = 0.0
    correct = 0.0
    device = next(model.parameters()).device

    num_iters = len(train_loader)
    model.train()
    for i, data in enumerate(train_loader, 0):

        inputs, labels = data

        optimizer.zero_grad()

        if lr_schedule is not None:
            lr = lr_schedule(i / num_iters)
            adjust_learning_rate(optimizer, lr)

        outputs = model(inputs.to(device))

        loss = criterion(outputs, labels.to(device))

        if regularizer is not None:
            loss += regularizer(model)

        # optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        loss_sum += loss.item() * len(labels)
        pred = outputs.data.argmax(1, keepdim=True)
        correct += pred.eq(labels.to(device).data.view_as(pred)).sum().item()


    return {
        'loss': loss_sum / len(train_loader.dataset),
        'accuracy': correct * 100.0 / len(train_loader.dataset),
    }





def test(test_loader, model, criterion, regularizer=None, **kwargs):
    loss_sum = 0.0
    nll_sum = 0.0
    correct = 0.0

    model.eval()
    device = next(model.parameters()).device

    for sample_input, target in test_loader:
        # sample_input = sample_input.cuda(async=True)
        # target = target.cuda(async=True)

        sample_input.to(device)
        target.to(device)

        output = model(sample_input, **kwargs)
        nll = criterion(output, target)
        loss = nll.clone()
        if regularizer is not None:
            loss += regularizer(model)

        nll_sum += nll.item() * sample_input.size(0)
        loss_sum += loss.item() * sample_input.size(0)
        pred = output.data.argmax(1, keepdim=True)
        correct += pred.eq(target.data.view_as(pred)).sum().item()

    return {
        'nll': nll_sum / len(test_loader.dataset),
        'loss': loss_sum / len(test_loader.dataset),
        'accuracy': correct * 100.0 / len(test_loader.dataset),
    }



def new_test(test_loader, model, criterion, regularizer=None, **kwargs):
    loss_sum = 0.0
    nll_sum = 0.0
    correct = 0.0

    model.eval()
    device = next(model.parameters()).device

    for batch in test_loader:
        sample_input = batch[0].to(device)
        target = batch[1].to(device)

        output = model(sample_input, **kwargs)
        nll = criterion(output, target)
        loss = nll.clone()
        if regularizer is not None:
            loss += regularizer(model)

        nll_sum += nll.item() * sample_input.size(0)
        loss_sum += loss.item() * sample_input.size(0)
        pred = output.data.argmax(1, keepdim=True)
        correct += pred.eq(target.data.view_as(pred)).sum().item()

    return {
        'nll': nll_sum / len(test_loader.dataset),
        'loss': loss_sum / len(test_loader.dataset),
        'accuracy': correct * 100.0 / len(test_loader.dataset),
    }




def predictions(test_loader, model, **kwargs):
    model.eval()
    preds = []
    targets = []
    for sample_input, target in test_loader:

        device = next(model.parameters()).device

        sample_input.to(device)
        target.to(device)

        # sample_input = sample_input.cuda(async=True)
        # output = model(sample_input, **kwargs)
        probs = F.softmax(output, dim=1)
        preds.append(probs.cpu().data.numpy())
        targets.append(target.numpy())
    return np.vstack(preds), np.concatenate(targets)


def isbatchnorm(module):
    return issubclass(module.__class__, torch.nn.modules.batchnorm._BatchNorm) or \
           issubclass(module.__class__, curves._BatchNorm)


def _check_bn(module, flag):
    if isbatchnorm(module):
        flag[0] = True


def check_bn(model):
    flag = [False]
    model.apply(lambda module: _check_bn(module, flag))
    return flag[0]


def reset_bn(module):
    if isbatchnorm(module):
        module.reset_running_stats()


def _get_momenta(module, momenta):
    if isbatchnorm(module):
        momenta[module] = module.momentum


def _set_momenta(module, momenta):
    if isbatchnorm(module):
        module.momentum = momenta[module]


def update_bn(loader, model, **kwargs):
    if not check_bn(model):
        return
    model.train()
    momenta = {}
    model.apply(reset_bn)
    model.apply(lambda module: _get_momenta(module, momenta))
    num_samples = 0
    for sample_input, _ in loader:
        device = next(model.parameters()).device
        sample_input.to(device)

        # sample_input = sample_input.cuda(async=True)
        batch_size = sample_input.data.size(0)

        momentum = batch_size / (num_samples + batch_size)
        for module in momenta.keys():
            module.momentum = momentum

        model(sample_input, **kwargs)
        num_samples += batch_size

    model.apply(lambda module: _set_momenta(module, momenta))
