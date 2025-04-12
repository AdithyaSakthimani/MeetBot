const WebSocket = require('ws');

const port = 8086;
const wss = new WebSocket.Server({ port });

wss.on('connection', function connection(ws) {
  console.log('Client connected');

  ws.on('message', function incoming(message) {
    const text = message.toString();
    console.log('Received transcription:', text);
  });
  ws.on('close', function () {
    console.log('Client disconnected');
  });
});

console.log(`WebSocket server is running on ws://localhost:${port}`);
