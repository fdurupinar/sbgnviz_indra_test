import sys
import time
import random
from socketIO_client import SocketIO

USER_ID_LEN = 32

def sa_callback(users):
    print 'Users:', ', '.join(x['userName'] for x in users)

def msg_callback(data):
    if isinstance(data, dict):
        print 'comment: <%(userName)s> %(comment)s' % data

_id_symbols = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890'
def generate_id(length, symbols=_id_symbols):
    n = len(symbols)
    symbol_gen = (symbols[random.randrange(0, n)] for i in range(length))
    return ''.join(symbol_gen)

if len(sys.argv) == 1:
    sbgn_file = 'output.sbgn'
else:
    sbgn_file = sys.argv[1]
with open(sbgn_file) as f:
    sbgn_content = f.read().decode('utf8')

socket = SocketIO('localhost', 3000)

sa_payload = {'userName': 'INDRA',
              'room': '6cbcf2d9-15ad-4be7-82a8-02b35672d88c',
              'userId': generate_id(USER_ID_LEN)}
alfr_payload = {'param': sbgn_content}

socket.on('message', msg_callback)

socket.emit('subscribeAgent', sa_payload, sa_callback)
#msg = "Hello from INDRA!"
#socket.emit('agentMessage', msg, lambda(args): None)
print "Loading model..."
socket.emit('agentNewFileRequest', {})
time.sleep(2)
socket.emit('agentLoadFileRequest', alfr_payload)
print "Running layout"
socket.emit('agentRunLayoutRequest', {})

try:
    socket.wait(3)
except KeyboardInterrupt:
    pass
print "Disconnecting..."
socket.emit('disconnect')
socket.disconnect()
