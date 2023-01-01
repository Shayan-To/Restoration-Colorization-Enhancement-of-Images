from script_dir import script_dir

import numpy as np
import matplotlib.pyplot as plt
import imageio
import scipy, scipy.misc, scipy.signal
import cv2
import sys
from enlighten_inference import EnlightenOnnxModel
from PIL import Image
import os

# Brightness Enhancement
def brightner(image):
    x = np.arange(255)
    b_image = (255) * (image / 255) ** 0.5
    b_image = np.array(b_image, dtype=np.uint8)
    return b_image


# Contrast Enhancement using CLAHE
def cLaHe(img):
    image_c = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    image_yuv = cv2.cvtColor(image_c, cv2.COLOR_BGR2YUV)
    clahe = cv2.createCLAHE(clipLimit=1, tileGridSize=(4, 4))
    image_yuv[:, :, 0] = clahe.apply(image_yuv[:, :, 0].astype(np.uint8))
    image_c_clahe = cv2.cvtColor(image_yuv, cv2.COLOR_YUV2BGR)
    clahe_image = cv2.cvtColor(image_c_clahe, cv2.COLOR_BGR2RGB)
    return clahe_image


# Ying Contrast Enhancement
def computeTextureWeights(fin, sigma, sharpness):
    dt0_v = np.vstack((np.diff(fin, n=1, axis=0), fin[0, :] - fin[-1, :]))
    dt0_h = np.vstack((np.diff(fin, n=1, axis=1).conj().T, fin[:, 0].conj().T - fin[:, -1].conj().T)).conj().T

    gauker_h = scipy.signal.convolve2d(dt0_h, np.ones((1, sigma)), mode='same')
    gauker_v = scipy.signal.convolve2d(dt0_v, np.ones((sigma, 1)), mode='same')

    W_h = 1 / (np.abs(gauker_h) * np.abs(dt0_h) + sharpness)
    W_v = 1 / (np.abs(gauker_v) * np.abs(dt0_v) + sharpness)

    return W_h, W_v


def solveLinearEquation(IN, wx, wy, lamda):
    [r, c] = IN.shape
    k = r * c
    dx = -lamda * wx.flatten('F')
    dy = -lamda * wy.flatten('F')
    tempx = np.roll(wx, 1, axis=1)
    tempy = np.roll(wy, 1, axis=0)
    dxa = -lamda * tempx.flatten('F')
    dya = -lamda * tempy.flatten('F')
    tmp = wx[:, -1]
    tempx = np.concatenate((tmp[:, None], np.zeros((r, c - 1))), axis=1)
    tmp = wy[-1, :]
    tempy = np.concatenate((tmp[None, :], np.zeros((r - 1, c))), axis=0)
    dxd1 = -lamda * tempx.flatten('F')
    dyd1 = -lamda * tempy.flatten('F')

    wx[:, -1] = 0
    wy[-1, :] = 0
    dxd2 = -lamda * wx.flatten('F')
    dyd2 = -lamda * wy.flatten('F')

    Ax = scipy.sparse.spdiags(np.concatenate((dxd1[:, None], dxd2[:, None]), axis=1).T, np.array([-k + r, -r]), k, k)
    Ay = scipy.sparse.spdiags(np.concatenate((dyd1[None, :], dyd2[None, :]), axis=0), np.array([-r + 1, -1]), k, k)
    D = 1 - (dx + dy + dxa + dya)
    A = ((Ax + Ay) + (Ax + Ay).conj().T + scipy.sparse.spdiags(D, 0, k, k)).T

    tin = IN[:, :]
    tout = scipy.sparse.linalg.spsolve(A, tin.flatten('F'))
    OUT = np.reshape(tout, (r, c), order='F')

    return OUT


def tsmooth(img, lamda=0.01, sigma=3.0, sharpness=0.001):
    I = cv2.normalize(img.astype('float64'), None, 0.0, 1.0, cv2.NORM_MINMAX)
    x = np.copy(I)
    wx, wy = computeTextureWeights(x, sigma, sharpness)
    S = solveLinearEquation(I, wx, wy, lamda)
    return S


def rgb2gm(I):
    if (I.shape[2] == 3):
        I = cv2.normalize(I.astype('float64'), None, 0.0, 1.0, cv2.NORM_MINMAX)
        I = np.abs((I[:, :, 0] * I[:, :, 1] * I[:, :, 2])) ** (1 / 3)

    return I


def applyK(I, k, a=-0.3293, b=1.1258):
    f = lambda x: np.exp((1 - x ** a) * b)
    beta = f(k)
    gamma = k ** a
    J = (I ** gamma) * beta
    return J


def entropy(X):
    tmp = X * 255
    tmp[tmp > 255] = 255
    tmp[tmp < 0] = 0
    tmp = tmp.astype(np.uint8)
    _, counts = np.unique(tmp, return_counts=True)
    pk = np.asarray(counts)
    pk = 1.0 * pk / np.sum(pk, axis=0)
    S = -np.sum(pk * np.log2(pk), axis=0)
    return S


def maxEntropyEnhance(I, isBad, a=-0.3293, b=1.1258):
    # Esatimate k
    tmp = cv2.resize(I, (50, 50), interpolation=cv2.INTER_AREA)
    tmp[tmp < 0] = 0
    tmp = tmp.real
    Y = rgb2gm(tmp)

    isBad = isBad * 1
    im_ = Image.fromarray((isBad * 255).astype(np.uint8))
    new_im = np.array(im_.resize((50, 50), Image.BICUBIC))
    isBad = new_im
    isBad[isBad < 0.5] = 0
    isBad[isBad >= 0.5] = 1
    Y = Y[isBad == 1]

    if Y.size == 0:
        J = I
        return J

    f = lambda k: -entropy(applyK(Y, k))
    opt_k = scipy.optimize.fminbound(f, 1, 7)

    # Apply k
    J = applyK(I, opt_k, a, b) - 0.01
    return J


def Ying_2017_CAIP(img, mu=0.5, a=-0.3293, b=1.1258):
    lamda = 0.5
    sigma = 5
    I = cv2.normalize(img.astype('float64'), None, 0.0, 1.0, cv2.NORM_MINMAX)

    # Weight matrix estimation
    t_b = np.max(I, axis=2)
    im = Image.fromarray((t_b * 255).astype(np.uint8))
    im_size = tuple((np.array(im.size) * 0.5).astype(int))
    new_im = np.array(im.resize(im_size, Image.BICUBIC))
    t_our = cv2.resize(tsmooth(new_im, lamda, sigma), (t_b.shape[1], t_b.shape[0]), interpolation=cv2.INTER_AREA)

    # Apply camera model with k(exposure ratio)
    isBad = t_our < 0.5
    J = maxEntropyEnhance(I, isBad)

    # W: Weight Matrix
    t = np.zeros((t_our.shape[0], t_our.shape[1], I.shape[2]))
    for i in range(I.shape[2]):
        t[:, :, i] = t_our
    W = t ** mu

    I2 = I * W
    J2 = J * (1 - W)

    result = I2 + J2
    result = result * 255
    result[result > 255] = 255
    result[result < 0] = 0
    return result.astype(np.uint8)


# Enlightnen GAN
def Enlighten(img):
    model = EnlightenOnnxModel()
    processed = model.predict(img)
    return processed


# Custom Funstion
def custom_function(img):
    f1 = brightner(img)
    f2 = cLaHe(img)
    f3 = Ying_2017_CAIP(img)
    f4 = Enlighten(img)
    out = ((f1.astype(np.int64) + 1.5 * f2.astype(np.int64) + f3.astype(np.int64) + 2 * f4.astype(
        np.int64) + img.astype(np.int64)) / 6.5).astype(np.uint8)
    return out


# Processing
ipt_path = f'{script_dir}/restored_output/'
out_path = f'{script_dir}/output_imgs/'
image_list = os.listdir(ipt_path)
for file in image_list:
    input_image = np.asarray(Image.open(os.path.join(ipt_path, file)).convert('RGB'))
    output_image = custom_function(input_image)
    plt.imsave(out_path + file[:-4] + '_enhanced.png', output_image)
