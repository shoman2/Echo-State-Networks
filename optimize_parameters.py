# Copyright 2019 Francesco Mannella (francesco.mannella@gmail.com) All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this fileexcept in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from __future__ import absolute_import
from matplotlib import rc
from __future__ import division
from __future__ import print_function

from ESN import EchoStateRNNCell
import matplotlib.pyplot as plt
import tensorflow.keras as keras
import tensorflow as tf
import numpy as np
import sys

# Configs ----------------------------------------------------------------------

# random numbers
random_seed = np.random.randint(1, 1e5)


# latex for matplotlib
rc('text', usetex=True)
plt.rcParams.update({'text.latex.preamble': r'\usepackage{amsmath}'})

# Utils ------------------------------------------------------------------------


def mackey_glass(stime=30000, dt=0.05,
                 beta=2., gamma=1., n=9.65, tau=2):
    d = tau//dt
    x = 3.0*np.ones(2*stime + d)
    for t in range(tau-1, 2*stime):
        x[t+1] = x[t] + dt*(
            beta*x[t-d] / (1.0 + x[t-d]**n)
            - gamma*x[t])
    return x[2*d: stime + 2*d], d


def mult_sines(stime=1200):
    res = np.arange(stime)
    res = np.sin(res) + np.sin(0.51*res) + np.sin(0.22*res) + \
        np.sin(0.1002*res) + np.sin(0.05343*res)

    res -= res.min()
    res /= res.max()

    return res

# tensorflow model -------------------------------------------------------------


class EchoStateOptimizer(keras.models.Model):
    def __init__(self, units, input_size, target, lmb=0.02, out_function=tf.tanh,
                 *args, **kargs):
        super(EchoStateOptimizer, self).__init__(*args, **kargs)

        self.cell = EchoStateRNNCell(units=units, activation=out_function,
                                     epsilon=0.08, decay=0.000001, alpha=0.5,
                                     optimize=True, optimize_vars=["rho", "decay",
                                                                   "alpha", "sw"])

        self.nn_layer = keras.layers.RNN(self.cell, return_sequences=True)

        self.units = units
        self.input_size = input_size
        self.lmb = tf.Variable(lmb, trainable=False)

    def call(self, x):

        inp, target = x

        nn_outputs = self.nn_layer(inp)
        readout_weights = self.ridge_regression(nn_outputs[0], target)
        y = tf.matmul(nn_outputs[0], readout_weights)

        return y

    def ridge_regression(self, X, Y):
        return tf.matmul(tf.linalg.inv(
            tf.matmul(tf.transpose(X), X) + self.lmb*tf.eye(self.units)),
            tf.matmul(tf.transpose(X), Y))


def optimize():

    # Global variables --------------------------------------------------------

    epochs = 50
    batches = 1
    stime = 700
    units = 20
    input_size = 1
    lr = 0.05
    lmb_init = 0.0995
    timewindow_begin = 50
    timewindow_end = stime

    # the activation function of the ESN
    out_function = tf.tanh

    # input -------------------------------------------------------------------

    rnn_input_size = np.zeros((batches, stime, input_size), dtype="float32")
    wave = mult_sines(stime+5).astype("float32")
    rnn_input_size = wave[5:].reshape(1, stime, 1)
    rnn_init_state = np.zeros([batches, units], dtype="float32")

    rnn_target = wave[:-5]
    rnn_target = rnn_target.reshape(stime, 1).astype("float32")

    inputs = wave[5:].reshape(1, stime, input_size) * np.ones([20, stime, input_size])
    inputs = inputs.astype("float32")
    targets = rnn_target.reshape(1, stime, 1) * np.ones([20, stime, 1])
    targets = targets.astype("float32")

    # model compile ------------------------------------------------------------

    data = {name: np.zeros(epochs) for name in ['loss', 'alpha', 'decay', 'rho', 'sw']}

    regression_model = EchoStateOptimizer(units=30, input_size=1,
                                          out_function=out_function,
                                          target=targets)
    optimizer = tf.optimizers.Adam(learning_rate=0.02)
    regression_model.compile(optimizer=optimizer, loss='mse')

    # Train --------------------------------------------------------------------

    for epoch in range(epochs):
        with tf.GradientTape() as tape:
            tape.watch(regression_model.trainable_variables)
            outputs = regression_model([inputs, targets])
            loss_ = tf.reduce_mean(tf.square(outputs - targets))
        grads = tape.gradient(loss_, regression_model.trainable_variables)

        regression_model.cell.decay.assign(tf.clip_by_value(
            regression_model.cell.decay, 0.0001, 0.25))
        regression_model.cell.alpha.assign(tf.clip_by_value(
            regression_model.cell.alpha, 0.05, 0.95))
        regression_model.cell.rho.assign(tf.clip_by_value(
            regression_model.cell.rho, 0.5, 50.0))
        regression_model.cell.sw.assign(tf.clip_by_value(
            regression_model.cell.sw, 0.5, 50.0))

        optimizer.apply_gradients(zip(grads, regression_model.trainable_variables))

        loss = loss_.numpy()
        data['loss'][epoch] = loss

        alpha = regression_model.cell.alpha.numpy()
        decay = regression_model.cell.decay.numpy()
        rho = regression_model.cell.rho.numpy()
        sw = regression_model.cell.sw.numpy()

        data['loss'][epoch] = loss
        data['alpha'][epoch] = alpha
        data['decay'][epoch] = decay
        data['rho'][epoch] = rho
        data['sw'][epoch] = sw

        print('    loss: %- 6.3f ' % loss, end='')
        print('   alpha: %- 6.3f ' % alpha, end='')
        print('   decay: %- 6.3f ' % decay, end='')
        print('     rho: %- 6.3f ' % rho, end='')
        print('      sw: %- 6.3f ' % sw, end='\n')

    # Plot graphs --------------------------------------------------------------

    plt.figure(figsize=(12, 8))

    plt.subplot(211)
    wave_line, = plt.plot(wave)

    plt.subplot(212)
    inp_line, = plt.plot(rnn_input_size[0, :, :])
    targ_line, = plt.plot(rnn_target)

    fig = plt.figure(figsize=(12, 8))
    plt.rcParams.update({'font.size': 22})

    ax1 = fig.add_subplot(211)
    loss, = ax1.plot(np.log10(data['loss']), lw=3)
    ax1.set_xlim([-10, epochs*1.5])
    ax1.set_xticks(np.arange(0, epochs*1.5, 10))
    ax1.set_xticklabels(np.arange(0, epochs*1.05, 10))
    yticks = ax1.get_yticks()
    ax1.get_yticklabels(["$10^{%3.2f}$" % y for y in yticks])
    ax1.set_xticklabels(np.arange(0, epochs*1.05, 10))

    ax1.legend([loss], ['log10 loss'])

    ax2 = fig.add_subplot(212)

    def rescale(x):
        xs = x - x.min()
        xs /= xs.max()
        return xs

    p_alpha, = ax2.plot(rescale(data['alpha']), lw=3)
    p_decay, = ax2.plot(rescale(data['decay']), lw=3)
    p_rho, = ax2.plot(rescale(data['rho']), lw=3)
    p_sw, = ax2.plot(rescale(data['sw']), lw=3)

    ax2.set_xlim([-10, epochs*1.5])
    ax2.set_ylim([-0.1, 1.1])
    ax2.set_xlim([-10, epochs*1.5])
    ax2.set_xticks(np.arange(0, epochs*1.5, 10))
    ax2.set_xticklabels(np.arange(0, epochs*1.05, 10))
    ax2.set_yticks([])

    ax2.legend([p_alpha, p_decay, p_rho, p_sw],
               ['alpha', 'decay', 'rho', 'sw'])

    np.save("data", [data])
    fig.savefig('loss.png')

# TEST -------------------------------------------------------------------------


if __name__ == "__main__":
    optimize()
