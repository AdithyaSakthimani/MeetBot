const WebSocket = require('ws');
const { Readable } = require('stream');
const fs = require('fs');
const path = require('path');

// Create output directory if it doesn't exist
const outputDir = path.join(__dirname, 'recordings');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir);
  console.log(`Created recordings directory: ${outputDir}`);
}

// Create a WebSocket server instance
const wss = new WebSocket.Server({ port: 8080, path: '/audio' });

console.log('WebSocket server started on port 8080 at path /audio');

// Keep track of active connections
let connections = 0;

wss.on('connection', (ws, req) => {
  connections++;
  console.log(`New client connected from ${req.socket.remoteAddress}`);
  console.log(`Active connections: ${connections}`);
  
  // Create a unique filename for this connection
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const sessionId = `session-${timestamp}-${Math.floor(Math.random() * 10000)}`;
  const pcmFilePath = path.join(outputDir, `${sessionId}.pcm`);
  const metadataFilePath = path.join(outputDir, `${sessionId}-metadata.json`);
  console.log(`Recording to file: ${pcmFilePath}`);
  
  let fileStream = fs.createWriteStream(pcmFilePath, { flags: 'a' });
  let audioMetadata = {
    sample_rate: 16000,
    channels: 1,
    format: 'audio/pcm'
  };
  let bytesReceived = 0;
  let metadataReceived = false;
  let lastSequence = -1;  // Track sequence numbers
  
  // Send connection acknowledgment
  ws.send(JSON.stringify({
    status: 'connected',
    sessionId: sessionId,
    message: 'Ready to receive audio data'
  }));
  
  // Ping to keep connection alive
  const pingInterval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.ping();
    }
  }, 30000);
  
  ws.on('message', (message) => {
    try {
      // All messages should now be JSON, try to parse
      try {
        let jsonMessage;
        if (message instanceof Buffer) {
          jsonMessage = JSON.parse(message.toString());
        } else {
          jsonMessage = JSON.parse(message.toString());
        }
        
        // Process based on event type
        if (jsonMessage.event === 'init') {
          // Handle initialization message
          audioMetadata = {
            sample_rate: jsonMessage.sample_rate || 16000,
            channels: jsonMessage.channels || 1,
            format: jsonMessage.format || 'audio/pcm',
            client_type: jsonMessage.client_type
          };
          
          // Write metadata to file
          fs.writeFileSync(metadataFilePath, JSON.stringify(audioMetadata, null, 2));
          console.log('Saved audio metadata:', audioMetadata);
          metadataReceived = true;
        }
        else if (jsonMessage.event === 'audio_data') {
          // Handle audio data (base64 encoded)
          if (jsonMessage.sequence !== undefined) {
            // Check for missing packets
            if (lastSequence !== -1 && jsonMessage.sequence !== lastSequence + 1) {
              console.log(`Warning: Sequence gap detected (expected ${lastSequence + 1}, got ${jsonMessage.sequence})`);
            }
            lastSequence = jsonMessage.sequence;
          }
          
          // Decode base64 audio data
          const audioData = Buffer.from(jsonMessage.data, 'base64');
          fileStream.write(audioData);
          bytesReceived += audioData.length;
          
          // Log less frequently
          if (bytesReceived % (100 * 1024) < 1024) {
            console.log(`Received ${(bytesReceived / (1024 * 1024)).toFixed(2)} MB of audio data`);
          }
        }
        else if (jsonMessage.event === 'stop') {
          console.log('Client requested stop:', jsonMessage.message);
        }
      } catch (parseError) {
        console.log('Error parsing message as JSON:', parseError);
        console.log('Raw message preview:', message.toString().substring(0, 50) + '...');
      }
    } catch (error) {
      console.error('Error processing message:', error);
    }
  });
  
  ws.on('close', (code, reason) => {
    connections--;
    console.log(`Client disconnected (code: ${code}, reason: ${reason || 'none'})`);
    console.log(`Active connections: ${connections}`);
    console.log(`Total audio data received: ${(bytesReceived / (1024 * 1024)).toFixed(2)} MB`);
    
    // Stop the ping interval
    clearInterval(pingInterval);
    
    // Close the file stream
    if (fileStream) {
      fileStream.end(() => {
        console.log(`PCM recording saved to ${pcmFilePath}`);
        
        // Check if the file has content
        try {
          const stats = fs.statSync(pcmFilePath);
          console.log(`File size: ${stats.size} bytes`);
          
          if (stats.size > 0) {
            // Convert to WAV if we have enough data
            convertPcmToWav(pcmFilePath, audioMetadata);
          } else {
            console.log('WARNING: PCM file is empty - no audio data was received');
          }
        } catch (e) {
          console.error('Error checking file stats:', e);
        }
      });
    }
  });
  
  ws.on('error', (error) => {
    console.error('WebSocket error:', error);
    clearInterval(pingInterval);
    if (fileStream) {
      fileStream.end();
    }
  });
});

/**
 * Convert PCM audio data to WAV format
 */
function convertPcmToWav(pcmFilePath, metadata) {
  try {
    const wavFilePath = pcmFilePath.replace('.pcm', '.wav');
    
    // Read the PCM data
    const pcmData = fs.readFileSync(pcmFilePath);
    
    if (pcmData.length === 0) {
      console.error('ERROR: PCM file is empty - no audio data was captured');
      return;
    }
    
    console.log(`Converting PCM to WAV: ${wavFilePath}`);
    console.log(`Sample rate: ${metadata.sample_rate}, Channels: ${metadata.channels}, Data size: ${pcmData.length} bytes`);
    
    // Create WAV header (44 bytes)
    const headerBuffer = Buffer.alloc(44);
    
    // RIFF chunk descriptor
    headerBuffer.write('RIFF', 0);                                  // ChunkID
    headerBuffer.writeUInt32LE(36 + pcmData.length, 4);             // ChunkSize
    headerBuffer.write('WAVE', 8);                                  // Format
    
    // fmt sub-chunk
    headerBuffer.write('fmt ', 12);                                 // Subchunk1ID
    headerBuffer.writeUInt32LE(16, 16);                             // Subchunk1Size (16 for PCM)
    headerBuffer.writeUInt16LE(1, 20);                              // AudioFormat (1 for PCM)
    headerBuffer.writeUInt16LE(metadata.channels, 22);              // NumChannels
    headerBuffer.writeUInt32LE(metadata.sample_rate, 24);           // SampleRate
    headerBuffer.writeUInt32LE(metadata.sample_rate * metadata.channels * 2, 28); // ByteRate
    headerBuffer.writeUInt16LE(metadata.channels * 2, 32);          // BlockAlign
    headerBuffer.writeUInt16LE(16, 34);                             // BitsPerSample
    
    // data sub-chunk
    headerBuffer.write('data', 36);                                 // Subchunk2ID
    headerBuffer.writeUInt32LE(pcmData.length, 40);                 // Subchunk2Size
    
    // Combine header and PCM data
    const wavBuffer = Buffer.concat([headerBuffer, pcmData]);
    
    // Write WAV file
    fs.writeFileSync(wavFilePath, wavBuffer);
    console.log(`Successfully converted PCM to WAV: ${wavFilePath}`);
  } catch (error) {
    console.error('Error converting PCM to WAV:', error);
  }
}

// For clean shutdown
process.on('SIGINT', () => {
  console.log('Shutting down server...');
  wss.clients.forEach(client => {
    client.close(1000, 'Server shutdown');
  });
  wss.close(() => {
    console.log('Server shutdown complete');
    process.exit(0);
  });
});

console.log(`Server is listening for WebSocket connections on ws://localhost:8080/audio`);
console.log(`Audio recordings will be saved to ${outputDir}`);
console.log('Press Ctrl+C to stop the server');