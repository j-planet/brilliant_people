import tensorflow as tf
import numpy as np

from models.abstract_model import AbstractModel
from data_readers import DataReader_Embeddings
from layers.rnn_layer import RNNLayer
from layers.fully_connected_layer import FullyConnectedLayer
from layers.dropout_layer import DropoutLayer
from layers.conv_maxpool_layer import ConvMaxpoolLayer


def convert_to_2d(t, d):
    newSecondD = np.product(d[1:])
    return tf.reshape(t, [-1, newSecondD]), newSecondD

class Model2(AbstractModel):

    def __init__(self, input_,
                 initialLearningRate, l2RegLambda,
                 numRnnOutputSteps, rnnNumCellUnits, rnnKeepProbs,
                 pooledKeepProb,
                 loggerFactory_=None):
        """        
        :type initialLearningRate: float 
        :type l2RegLambda: float
        :type rnnNumCellUnits: list
        :type numRnnOutputSteps: int 
        :type rnnKeepProbs: Union[list, float]
        :type pooledKeepProb: float 
        """

        if type(rnnKeepProbs) == float:
            assert 0 < rnnKeepProbs <= 1
            rnnKeepProbs = [rnnKeepProbs] * len(rnnNumCellUnits)

        assert len(rnnNumCellUnits) == len(rnnNumCellUnits)
        assert 0.0 < pooledKeepProb <= 1

        self.l2RegLambda = l2RegLambda
        self.numRnnOutputSteps = numRnnOutputSteps
        self.rnnNumCellUnits = rnnNumCellUnits
        self.rnnKeepProbs = rnnKeepProbs
        self.pooledKeepProb = pooledKeepProb

        super().__init__(input_, initialLearningRate, loggerFactory_)
        self.print('l2 reg lambda: %0.7f' % l2RegLambda)

    def make_graph(self):

        layer1 = self.add_layer(RNNLayer.new(
            self.rnnNumCellUnits, numStepsToOutput_ = self.numRnnOutputSteps), self.input, (-1, -1, self.vecDim))

        # just last row of the rnn output
        layer2a_output = layer1.output[:,-1,:]
        layer2a_outputshape = (layer1.output_shape[0], layer1.output_shape[2])

        layer2b = ConvMaxpoolLayer(layer1.output, layer1.output_shape,
                                   convParams_={'filterShape': (2, 2), 'numFeaturesPerFilter': 16, 'activation': 'relu'},
                                   maxPoolParams_={'ksize': (self.numRnnOutputSteps, 1), 'padding': 'SAME'},
                                   loggerFactory=self.loggerFactory)
        layer2b_output, layer2b_output_numcols = convert_to_2d(layer2b.output, layer2b.output_shape)


        layer2c = ConvMaxpoolLayer(layer1.output, layer1.output_shape,
                                   convParams_={'filterShape': (4, 4), 'numFeaturesPerFilter': 16, 'activation': 'relu'},
                                   maxPoolParams_={'ksize': (self.numRnnOutputSteps, 1), 'padding': 'SAME'},
                                   loggerFactory=self.loggerFactory)
        layer2c_output, layer2c_output_numcols = convert_to_2d(layer2c.output, layer2c.output_shape)

        layer2_output = tf.concat([layer2a_output, layer2b_output, layer2c_output], axis=1)
        layer2_output_numcols = layer2a_outputshape[1] + layer2b_output_numcols + layer2c_output_numcols

        self.layers.append([layer2b, layer2c])
        self.outputs.append({'output': layer2_output,
                             'output_shape': (layer2a_outputshape[0], layer2_output_numcols)})

        self.add_layer(DropoutLayer.new(self.pooledKeepProb))

        lastLayer = self.add_layer(FullyConnectedLayer.new(self.numClasses))

        self.l2Loss = self.l2RegLambda * (tf.nn.l2_loss(lastLayer.weights) + tf.nn.l2_loss(lastLayer.biases))




if __name__ == '__main__':

    datadir = '../data/peopleData/2_samples'
    # datadir = '../data/peopleData/earlyLifesWordMats/politician_scientist'

    lr = 1e-3
    dr = DataReader_Embeddings(datadir, 'bucketing', 40, 30)
    model = Model2(dr.input, lr, 0, 4, [8], 1, 1)

    sess = tf.InteractiveSession()
    sess.run(tf.global_variables_initializer())

    for step in range(100):
        if step % 10 == 0:
            print('Lowering learning rate to', lr)
            lr *= 0.9
            model.assign_lr(sess, lr)

        fd = dr.get_next_training_batch()[0]
        _, c, acc = model.train_op(sess, fd, True)
        print('Step %d: (cost, accuracy): training (%0.3f, %0.3f)' % (step, c, acc))