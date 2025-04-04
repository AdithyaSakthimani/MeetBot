const WebSocket = require('ws');

const wss = new WebSocket.Server({ port: 8765 });
const clients = new Set();

wss.on('connection', (ws) => {
  console.log('A user connected');
  clients.add(ws);

  ws.on('message', (message) => {
    for (let client of clients) {
      if (client !== ws && client.readyState === WebSocket.OPEN) {
        client.send(message);
      }
    }
  });

  ws.on('close', () => {
    console.log('A user disconnected');
    clients.delete(ws);
  });
});

console.log("WebSocket server running on ws://localhost:8765");
