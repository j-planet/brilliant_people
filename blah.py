from pprint import pprint
from time import time
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='0'  # Defaults to 0: all logs; 1: filter out INFO logs; 2: filter out WARNING; 3: filter out errors
import tensorflow as tf
from tensorflow.python.client.timeline import Timeline
from tensorflow.contrib.rnn import BasicLSTMCell, BasicRNNCell, static_bidirectional_rnn, MultiRNNCell, DropoutWrapper

from data_reader import DataReader
from utilities import tensorflowFilewriter


st = time()
sess = tf.InteractiveSession()

PATCH_TO_FULL = False

# with tf.device('/cpu:0'):

def print_log_str(x_, y_, xLengths_, names_):
    """
    :return a string of loss and accuracy
    """

    # feedDict = {x: x_, y: y_}
    feedDict = {x: x_, y: y_, sequenceLength: xLengths_, outputKeepProb: outputKeepProbConstant}

    print('loss = %.3f, accuracy = %.3f' % \
          tuple(sess.run([cost, accuracy], feed_dict=feedDict)))

    labels = dataReader.get_classes_labels()
    trueYInds, predYInds = sess.run([trueY, pred], feed_dict=feedDict)

    print('True label became... --> ?')

    for i, name in enumerate(names_):
        print('%s: %s --> %s %s' % (name, labels[trueYInds[i]], labels[predYInds[i]], '(wrong)' if trueYInds[i]!=predYInds[i] else '' ))


logger_train = tensorflowFilewriter('./logs/train')
logger_train.add_graph(sess.graph)

# ================== DATA ===================
dataReader = DataReader(vectorFilesDir='./data/peopleData/4_samples')
# dataReader = DataReader(vectorFilesDir='./data/peopleData/earlyLifesWordMats_6B50d/politician_scientist')

# ================== CONFIG ===================

# --------- network ---------
vecDim = 300
numHiddenLayerFeatures = 128
numRnnLayers = 3
outputKeepProbConstant = 1.

numClasses = len(dataReader.get_classes_labels())
outputKeepProb = tf.placeholder(tf.float32)

# --------- running ---------
learningRate = 0.1
numSteps = 30     # 1 step runs 1 batch
batchSize = 5

logTrainingEvery = 1
logValidationEvery = 5

print('====== CONFIG: SHUFFLED %d hidden layers with %d features each; '
      'dropoutKeep = %0.2f'
      ' batch size %d, learning rate %.3f'
      % (numRnnLayers, numHiddenLayerFeatures, outputKeepProbConstant, batchSize, learningRate))

# ================== GRAPH ===================
x = tf.placeholder(tf.float32, [None, None, vecDim])
# x = tf.placeholder(tf.float32, [None, dataReader.get_max_len(), vecDim])
y = tf.placeholder(tf.float32, [None, numClasses])
sequenceLength = tf.placeholder(tf.int32)

# weights = tf.Variable(tf.random_normal([numHiddenLayerFeatures, numClasses]))
weights = tf.Variable(tf.random_normal([2*numHiddenLayerFeatures, numClasses]))
biases = tf.Variable(tf.random_normal([numClasses]))

# make LSTM cells
# cell_forward = BasicLSTMCell(numHiddenLayerFeatures)
# cell_backward = BasicLSTMCell(numHiddenLayerFeatures)

cell_forward = MultiRNNCell([DropoutWrapper(BasicLSTMCell(numHiddenLayerFeatures), output_keep_prob=outputKeepProb)] * numRnnLayers)
cell_backward = MultiRNNCell([DropoutWrapper(BasicLSTMCell(numHiddenLayerFeatures), output_keep_prob=outputKeepProb)] * numRnnLayers)

outputs, _ = tf.nn.bidirectional_dynamic_rnn(cell_forward, cell_backward,
                                             time_major=False, inputs=x, dtype=tf.float32,
                                             sequence_length=sequenceLength,
                                             swap_memory=True)

# wrap RNN around LSTM cells
# baseCell = BasicLSTMCell(numHiddenLayerFeatures)
# baseCellWDropout = DropoutWrapper(baseCell, output_keep_prob=outputKeepProb)
# multiCell = MultiRNNCell([baseCell]*numRnnLayers)
# outputs, _ = tf.nn.dynamic_rnn(multiCell,
#                                time_major=False, inputs=x, dtype=tf.float32,
#                                sequence_length=sequenceLength,
#                                swap_memory=True)

# cost and optimize
logits = tf.matmul(tf.concat(outputs, 2)[:,-1,:], weights) + biases
cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=y))
optimizer = tf.train.AdamOptimizer(learning_rate=learningRate).minimize(cost)

# predictions and accuracy
pred = tf.argmax(logits, 1)
trueY = tf.argmax(y, 1)
accuracy = tf.reduce_mean(tf.cast(
    tf.equal(pred, trueY)
    , tf.float32))

# train
sess.run(tf.global_variables_initializer())
dataReader.start_batch_from_beginning()     # technically unnecessary

# run_metadata = tf.RunMetadata()

for step in range(numSteps):

    print('\nStep %d (%d data points):' % (step, step * batchSize))

    # will prob need some shape mangling here
    batchX, batchY, xLengths, names = dataReader.get_next_training_batch(batchSize, patchTofull_=PATCH_TO_FULL, verbose_=False)
    # feedDict = {x: batchX, y: batchY}
    feedDict = {x: batchX, y: batchY, sequenceLength: xLengths, outputKeepProb: outputKeepProbConstant}

    sess.run(optimizer, feed_dict=feedDict)
    # options=tf.RunOptions(trace_level=tf.RunOptions.SOFTWARE_TRACE),
    # run_metadata=run_metadata)

    # print('here')
    # trace = Timeline(step_stats=run_metadata.step_stats)
    # print('done with here')

    # print evaluations
    if step % logTrainingEvery == 0:
        print_log_str(batchX, batchY, xLengths, names)

        if step % logValidationEvery == 0:
            print('\n>>> Validation:')
            print_log_str(*(dataReader.get_validation_data(patchTofull_=PATCH_TO_FULL)))


print('\n>>>>>> Test:')
print_log_str(*(dataReader.get_test_data(patchTofull_=PATCH_TO_FULL)))

print('Time elapsed:', time()-st)

# trace_file = open('timeline.ctf.json', 'w')
# trace_file.write(trace.generate_chrome_trace_format())
