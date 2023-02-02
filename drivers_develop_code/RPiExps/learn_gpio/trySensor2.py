import RPi.GPIO as GPIO

PIPin  = 11

def setup():
    GPIO.setmode(GPIO.BOARD)       # Numbers GPIOs by physical location
    GPIO.setup(PIPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)    # Set BtnPin's mode is input, and pull up to high level(3.3V)
    GPIO.add_event_detect(PIPin, GPIO.BOTH, callback=detect, bouncetime=10)

def Print(x):   #打印光线被遮挡提示消息
    if x == 1:
        print('    *************************')
        print('    *   Light was blocked   *')
        print('    *************************')

def detect(chn):
    Print(GPIO.input(PIPin))    #打印光线被遮挡提示消息

def loop():
    while True:
        pass  #pass语句就是空语句
def destroy():
    GPIO.cleanup()             # Release resource

if __name__ == '__main__':     # Program start from here
    setup()
    try:
        loop()
    except KeyboardInterrupt:  # When 'Ctrl+C' is pressed, the child program destroy() will be  executed.
        destroy()