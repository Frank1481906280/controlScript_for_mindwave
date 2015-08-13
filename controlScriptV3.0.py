from Queue import Queue
from math import sqrt
from mindwavemobile.MindwaveMobileRawReader import MindwaveMobileRawReader
from mindwavemobile.MindwaveDataPoints import RawDataPoint
import mindwavemobile.MindwaveDataPointReader as MindwaveDataPointReader
import blinkData2
import bluetooth
import threading
import serial
import time
import re


data = None
dataCon = threading.Condition()  # 用于data的线程跳转条件函数
rawDataQueue = Queue()  # 用于rawData的线程同步队列
corner = 0  # 角落位置


def turnON():  # 向蓝牙发送AAbbb，打开电器
    global ser
    ser.write('AAbbb')


def turnOff():  # 向蓝牙发送AAccc，关闭电器
    global ser
    ser.write('AAccc')


# 本线程作用：读取mindwave的原始数据和meditation等数据
# 改版后的这个class很纯净，只读数据不做分析
# 利用同步队列，把分析的工作移到了其他class中，以免分析耗时对mindwve读数据的动作造成堵塞
class MindWave(threading.Thread):

    def __init__(self, MindwaveDataPointReader):
        threading.Thread.__init__(self)
        self.MindwaveDataPointReader = MindwaveDataPointReader

    def run(self):
        i = 0
        dataTemp = []
        global rawDataQueue
        global data

        if (self.MindwaveDataPointReader.isConnected()):
            while(True):
                dataPoint = self.MindwaveDataPointReader.readNextDataPoint()
                if (dataPoint.__class__ is RawDataPoint):
                    raw = dataPoint.rawValue
                    rawDataQueue.put(raw)  # 利用队列通知blinkControl线程取出rawData并进行分析
                else:
                    if (i == 0):
                        dataTemp.append(dataPoint.meditationValue)
                    elif (i == 1):
                        dataTemp.append(dataPoint.attentionValue)
                    elif (i == 2):
                        dataTemp.append(dataPoint.delta)
                        dataTemp.append(dataPoint.theta)
                        dataTemp.append(dataPoint.lowAlpha)
                        dataTemp.append(dataPoint.highAlpha)
                        dataTemp.append(dataPoint.lowBeta)
                        dataTemp.append(dataPoint.highBeta)
                        dataTemp.append(dataPoint.lowGamma)
                        dataTemp.append(dataPoint.midGamma)
                    elif (i == 3):
                        signal_val = dataPoint.amountOfNoise
                        if (signal_val == 0):  # 信号强度好，本次数据有效
                            dataCon.acquire()  # 线程锁
                            data = dataTemp
                            dataCon.notifyAll()  # 通知其他线程，data数据已更新
                            dataCon.release()  # 释放锁
                    else:
                        dataTemp = []
                        i = 0
                        dataTemp.append(dataPoint.meditationValue)
                    i = i + 1


# 本线程作用：判断是否眨眼
# 利用了同步队列对rawData进行处理
# 同时又使用了内部的多线程，使得每次第一次眨眼时就开启计时器
# 计时器用于计算规定时间内的眨眼次数
class BlinkControl(threading.Thread):

    def __init__(self, blinkTrainData, threshold, waitingTime):
        threading.Thread.__init__(self)
        self.blinkTrainData = blinkTrainData
        self.threshold = threshold  # 拟合度的阀值
        self.waitingTime = waitingTime  # 计算眨眼次数的规定时间
        self.Con = threading.Condition()
        self.rawData = []
        self.blinkTimes_in_Thread = 0  # 在规定时间内的眨眼次数

    def control(self):  # 该函数用于描述相应眨眼次数相应的动作。实践时主要改动这个函数就可以
        if self.blinkTimes_in_Thread == 1:
            print 'You have blinked 1 time in %s seconds to do nothing\n'% (self.waitingTime)

        elif self.blinkTimes_in_Thread == 2:
            print 'You have blinked 2 times in %s seconds to do A\n'% (self.waitingTime)

        elif self.blinkTimes_in_Thread == 3:
            print 'You have blinked 3 times in %s seconds to do B\n'% (self.waitingTime)

        elif self.blinkTimes_in_Thread == 4:
            print 'You have blinked 4 times in %s seconds to close the Fan\n'% (self.waitingTime)
            # self.ser.write('AAbbb')

        elif self.blinkTimes_in_Thread > 5:
            print 'You have blinked more than 5 times in %s seconds\n'% (self.waitingTime)

        else:
            print 'You have blinked %s times in %s seconds but I don\'t know to do what\n'% (self.blinkTimes_in_Thread, self.waitingTime)

    def pearson(self, T1, T2, cnt):  # 核心算法，皮尔逊相关系数
        sum1 = sum(T1)
        sum2 = sum(T2)
        sqSum1 = sum(pow(num, 2) for num in T1)
        sqSum2 = sum(pow(num, 2) for num in T2)
        mulSum = sum(T1[i]*T2[i] for i in range(cnt))
        son = mulSum-sum1*sum2/cnt
        mot = sqrt((sqSum1-pow(sum1, 2)/cnt) * (sqSum2-pow(sum2, 2)/cnt))
        if mot == 0:
            r = 0
        else:
            r = son/mot
        return r

    def isBlink(self):  # 该函数判断是否眨眼，每次眨眼，blinkTimes_in_Thread加一
        global rawDataQueue
        isBlink = 0
        BlinkLength = len(self.blinkTrainData)

        while True:
            self.rawData.append(rawDataQueue.get())  # 等待mindwave线程的rawData
            if len(self.rawData) > BlinkLength:  # 数据长度大于样本数据
                self.rawData.pop(0)  # 丢掉已分析过的rawData
            if len(self.rawData) == BlinkLength:  # 长度相等
                fitRate = self.pearson(
                    self.blinkTrainData, self.rawData, BlinkLength)  # 拟合度
                if fitRate > self.threshold:  # 拟合度达标
                    if isBlink == 0:
                        self.Con.acquire()  # 拿到线程锁，可以开始计数
                        self.blinkTimes_in_Thread += 1
                        self.Con.notify()  # 通知另一个线程timer判断并开启计时器
                        print 'blinked %s times in %s s' % (self.blinkTimes_in_Thread, self.waitingTime)
                        isBlink = 1  # 标记，用于辅助判断是否眨眼
                        self.Con.release()  # 释放锁
                else:
                    isBlink = 0

    def timer(self):  # 该函数即计时器
        while True:
            self.Con.acquire()
            self.Con.wait()  # 等待。直至线程isBlink通知
            if self.blinkTimes_in_Thread == 1:  # 得到线程isBlink的通知，且是第一次眨眼，开启计时器
                self.Con.release()
                time.sleep(self.waitingTime)  # 计时开始
                print 'time out'  # 计时结束
                self.Con.acquire()
                print 'total blinked %s times in %s s' % (self.blinkTimes_in_Thread, self.waitingTime)
                self.control()
                self.blinkTimes_in_Thread = 0  # 清零眨眼次数
                self.Con.release()
            else:
                self.Con.release()

    def run(self):
        blinkThread = threading.Thread(target=self.isBlink)
        blinkThread.setDaemon(True)
        blinkThread.start()
        self.timer()  # 以上，开启两个子线程，分别用于检测眨眼和判断是否开始计时


# 该线程可用于（每隔0.1秒）判断在哪个角落和向该角落发出打开或关闭电器的控制信号
class CornerControl(threading.Thread):

    def __init__(self, level):
        threading.Thread.__init__(self)
        self.level = level  # 冥想度-专注度的控制阀值

    def control(self):
        global data

        dataCon.acquire()
        dataCon.wait()  # 得到线程mindwave的通知
        Data = data  # 得到通知之后，取得已更新的data
        dataCon.release()
        if (abs(Data[0] - Data[1]) > self.level):
            turnON()  # 如果新的data达到阀值的话，打开电器

    def whichCorner(self):  # 用于判断在哪个角落。不过这个函数作用不大，因此这里也没用到
        global corner
        global ser

        while True:
            btData = ser.readline()
            if('0xC4BE84058E7D' in btData):
                if corner != 1:
                    print '\nYou are on the corner 1\n'
                    corner = 1

            elif('0xC4BE84057C8E' in btData):
                if corner != 2:
                    print '\nYou are on the corner 2\n'
                    corner = 2

            time.sleep(0.1)

    def run(self):
        self.control()  # 线程的主程序只用到发送控制信号的那个


# 心情指标。用冥想度-专注度的绝对值作为心情指标
# 虽然挺扯蛋，但是没过一段时间有一段字跟你说你的心情指标是80或90，还是挺好玩的
# 经过我熬夜的认证，准确度一般，但是唬唬人还是可以的
class SpiritIndexs(threading.Thread):

    def __init__(self, waitingTime=30):
        threading.Thread.__init__(self)
        self.waitingTime = waitingTime  # 统计的时间，比如每30秒统计一次心情
        self.lock = threading.RLock()  # 内部的线程锁
        self.spiritIndex = 0

    def spiritCounter(self):
        global data

        while True:
            dataCon.acquire()
            dataCon.wait()  # 等待mindwave线程的通知
            Data = data  # 得到线程通知后拿到更新后的data
            dataCon.release()
            self.lock.acquire()
            self.spiritIndex += abs(Data[0]-Data[1])  # 利用冥想度和专注度作为心情指标
            self.lock.release()

    def run(self):
        counter = threading.Thread(target=self.spiritCounter)
        counter.setDaemon(True)
        counter.start()

        while True:
            time.sleep(self.waitingTime)  # 开始计时
            self.lock.acquire()  # 计时结束
            spiritIndex_ave = 100-self.spiritIndex/float(self.waitingTime)  # 计算平均指标
            self.spiritIndex = 0  # 清零
            self.lock.release()
            print '%.2f mins past.Your average spiritIndex was %.2f' % (self.waitingTime/60.0, spiritIndex_ave)


# 这个线程是用于多线程同步的测试的，不用理会这个
class Test(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        global data

        while True:
            dataCon.acquire()
            dataCon.wait()
            Data = data
            dataCon.release()
            print '\nthe data:'
            print Data,'\n'


# 下面这一句是指链接上蓝牙模块
# ser = serial.Serial('/dev/ttyUSB0', 115200)

# 取得眨眼的样本数据
blinkTrainData = blinkData2.dataB[:90]

# 开启mindwave线程
MindwaveDataPointReader = MindwaveDataPointReader.MindwaveDataPointReader()
MindwaveDataPointReader.start()
mindWaveThread = MindWave(MindwaveDataPointReader)
mindWaveThread.setDaemon(True)
mindWaveThread.start()

# 开启角落线程，没有链接蓝牙因此这里先关掉了即先注释掉
# cornerControl = CornerControl(ser, 30)
# cornerControl.start()
# print 'CornerControl start'

# 开启眨眼检测线程
blinkControl = BlinkControl(blinkTrainData, 0.9, 2)
blinkControl.setDaemon(True)
blinkControl.start()
print 'BlinkControl start'

# 开启心情指标检测的线程
spiritIndexs = SpiritIndexs(5)
spiritIndexs.setDaemon(True)
spiritIndexs.start()
print 'SpiritIndexs start'

# 测试的线程，已关掉
# test = Test()
# test.setDaemon(True)
# test.start()

blinkControl.join()
