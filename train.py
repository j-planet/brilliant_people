import os
from time import time

os.environ['TF_CPP_MIN_LOG_LEVEL']='0'  # Defaults to 0: all logs; 1: filter out INFO logs; 2: filter out WARNING; 3: filter out errors
import tensorflow as tf

from utilities import tensorflowFilewriters, label_comparison, LoggerFactory, create_time_dir, dir_create_n_clear



def evaluate_in_batches(sess, batchGenerator_, classLabels_, evaluationFunc_, logFunc_=None, verbose_=True):
    logFunc_ = logFunc_ or print

    # data = dataReader.get_data_in_batches(batchSize_, validateOrTest_)

    totalCost = 0
    totalAccuracy = 0
    allTrueYInds = []
    allPredYInds = []
    allNames = []

    # d: x, y, xLengths, names
    for fd, names in batchGenerator_:
        c, acc, trueYInds, predYInds = evaluationFunc_(sess, fd)

        actualCount = len(trueYInds)
        totalCost += c * actualCount
        totalAccuracy += acc * actualCount
        allNames += list(names)
        allTrueYInds += list(trueYInds)
        allPredYInds += list(predYInds)

    assert len(allTrueYInds) == len(allPredYInds) == len(allNames)

    avgCost = totalCost / len(allTrueYInds)
    avgAccuracy = totalAccuracy / len(allTrueYInds)

    logFunc_('-------------')
    logFunc_('loss = %.3f, accuracy = %.3f' % (avgCost, avgAccuracy))
    if verbose_:
        label_comparison(allTrueYInds, allPredYInds, allNames, classLabels_, logFunc_)
    logFunc_('-------------')

    return avgCost, avgAccuracy


def log_progress(step, numDataPoints, lr, c=None, acc=None, logFunc=None):

    res = 'Step %d (%d data pts); lr = %.6f' % (step, numDataPoints, lr)

    if c is not None: res += '; loss = %.3f' % c
    if acc is not None: res += ', accuracy = %.3f' % acc

    (logFunc or print)(res)

    return res


# def evaluate_stored_model(dataDir, modelScale, savePath, batchSize):
#
#     dataReader = DataReader(dataDir, 'bucketing', batchSize)
#     model = Model(modelScale, dataReader.input, dataReader.numClasses, 0)
#
#     tf.train.Saver().restore(sess, savePath)
#
#     evaluate_in_batches(dataReader.get_test_data_in_batches(), dataReader.classLabels, model.evaluate)


def train(sess, dataReaderMaker, modelMaker, runScale, baseLogDir):

    """
    :param dataReaderMaker: lambda 'bucketing', runConfig.batchSize, 40, loggerFactory: dataReader
    """

    assert runScale in ['basic', 'tiny', 'small', 'full']

    logDir = create_time_dir(baseLogDir)

    def _decrease_learning_rate(numDataPoints_, lowerBound_=1e-7):
        """
        :type numDataPoints_: int
        """

        lrDecay = lrDecayPerCycle ** (numDataPoints_ / dataReader.trainSize)
        newLr = max(initialLr * lrDecay, lowerBound_)
        model.assign_lr(sess, newLr)

        return newLr

    st = time()

    loggerFactory = LoggerFactory(logDir)
    runConfig = RunConfig(runScale, loggerFactory)
    # dataReader = DataReader_Embeddings(dataDir, 'bucketing', runConfig.batchSize, 40, loggerFactory)
    dataReader = dataReaderMaker(bucketingOrRandom='bucketing', batchSize_=runConfig.batchSize, minimumWords=40, loggerFactory=loggerFactory)
    model = modelMaker(dataReader.input, loggerFactory)
    initialLr = model.initialLearningRate

    # =========== set up tensorboard ===========
    train_writer, valid_writer = tensorflowFilewriters(logDir)
    train_writer.add_graph(sess.graph)
    trainLogFunc = loggerFactory.getLogger('run.train').info
    validLogFunc = loggerFactory.getLogger('run.validate').info
    testLogFunc = loggerFactory.getLogger('run.test').info

    # =========== TRAIN!! ===========
    sess.run(tf.global_variables_initializer())
    saver, savePath = tf.train.Saver(), os.path.join(dir_create_n_clear(logDir, 'saved'), 'save.ckpt')
    trainLogFunc('Saving to ' + savePath)
    dataReader.start_batch_from_beginning()     # technically unnecessary
    batchSize, numSteps, logValidationEvery = runConfig.batchSize, runConfig.numSteps, runConfig.logValidationEvery
    bestValidC, bestValidAcc, numValidWorse = 100, 0, 0   # for early stopping if the model isn't getting anywhere :(
    lrDecayPerCycle = 0.9

    for step in range(numSteps):
        numDataPoints = (step+1) * runConfig.batchSize

        lr = _decrease_learning_rate(numDataPoints)
        summaries, c, acc = model.train_op(sess, dataReader.get_next_training_batch()[0], computeMetrics_=True)

        train_writer.add_summary(summaries, step * batchSize)

        log_progress(step, numDataPoints, lr, c, acc, trainLogFunc)

        if step % logValidationEvery == 0:
            curValidC, curValidAcc = evaluate_in_batches(sess, dataReader.get_validation_data_in_batches(), dataReader.classLabels, model.evaluate, validLogFunc, verbose_=False)
            saver.save(sess, savePath, global_step=numDataPoints)

            if curValidC >= bestValidC and curValidAcc <= bestValidAcc:
                numValidWorse += 1
                lrDecayPerCycle *= 0.95
                validLogFunc('Worse than best validation result so far %d time(s). Decreasing lrDecayPerCycle to %0.3f.' % (numValidWorse, lrDecayPerCycle))

                if numValidWorse >= runConfig.failToImproveTolerance:
                    validLogFunc('Results have not improved in %d validations. Quitting.' % numValidWorse)
                    break
            else:
                bestValidC = min(bestValidC, curValidC)
                bestValidAcc = max(bestValidAcc, curValidAcc)
                numValidWorse = 0


    testLogFunc('Time elapsed: %0.3f ' % (time()-st) )
    evaluate_in_batches(sess, dataReader.get_test_data_in_batches(), dataReader.classLabels, model.evaluate, testLogFunc, verbose_=True)

    saver.save(sess, savePath)
    train_writer.close()
    valid_writer.close()


class RunConfig(object):
    def __init__(self, scale, loggerFactory=None):
        assert scale in ['basic', 'tiny', 'small', 'medium', 'full']

        if scale == 'basic':
            self.numSteps = 5
            self.batchSize = 2
            self.logValidationEvery = 3
            self.failToImproveTolerance = 1

        elif scale == 'tiny':
            self.numSteps = 10
            self.batchSize = 20
            self.logValidationEvery = 3
            self.failToImproveTolerance = 1

        elif scale == 'small':
            self.numSteps = 100
            self.batchSize = 50
            self.logValidationEvery = 5
            self.failToImproveTolerance = 2

        elif scale == 'medium':
            self.numSteps = 200
            self.batchSize = 100
            self.logValidationEvery = 10
            self.failToImproveTolerance = 3

        elif scale == 'full':
            self.numSteps = 1000
            self.batchSize = 200
            self.logValidationEvery = 12
            self.failToImproveTolerance = 4

        self.scale = scale
        self._logFunc = print if loggerFactory is None else loggerFactory.getLogger('config.run').info
        self.print()

    def print(self):
        self._logFunc('batch size %d, validation worse run tolerance %d' % (self.batchSize, self.failToImproveTolerance))


def run_thru_params(dataReaderMaker, modelMakers, runScale, baseLogDir, useCPU=True):
    """
    :type modelMakers: list 
    :type runScale: str
    :type baseLogDir: str
    :type useCPU: bool
    :return: 
    """

    for mk in modelMakers:

        tf.reset_default_graph()

        if useCPU:
            with tf.device('/cpu:0'):
                sess = tf.InteractiveSession(config=tf.ConfigProto(allow_soft_placement=True))

                train(sess, dataReaderMaker, mk, runScale, baseLogDir)
        else:
            sess = tf.InteractiveSession(
                config=tf.ConfigProto(gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=0.85),
                                      allow_soft_placement=True))

            train(sess, dataReaderMaker, mk, runScale, baseLogDir)
