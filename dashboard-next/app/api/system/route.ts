import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import os from 'os';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const hostname = os.hostname();
    const uptime = os.uptime();
    const cpus = os.cpus();
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const loadAvg = os.loadavg();

    // Check daemon heartbeat
    const heartbeatFile = path.join(os.homedir(), '.claude-fleet', 'daemon-heartbeat');
    let daemonAlive = false;
    if (fs.existsSync(heartbeatFile)) {
      const stat = fs.statSync(heartbeatFile);
      daemonAlive = Date.now() - stat.mtimeMs < 120000; // 2 min
    }

    // Check tmux sessions
    let tmuxSessions: string[] = [];
    try {
      const output = execSync('tmux list-sessions -F "#{session_name}" 2>/dev/null', {
        timeout: 5000,
      }).toString().trim();
      tmuxSessions = output ? output.split('\n') : [];
    } catch {
      // tmux not running
    }

    return NextResponse.json({
      hostname,
      uptime,
      cpu_count: cpus.length,
      cpu_model: cpus[0]?.model || 'unknown',
      load_avg: loadAvg,
      memory: {
        total: totalMem,
        free: freeMem,
        used: totalMem - freeMem,
        percent: ((totalMem - freeMem) / totalMem * 100).toFixed(1),
      },
      daemon_alive: daemonAlive,
      tmux_sessions: tmuxSessions,
    });
  } catch (error) {
    console.error('Error getting system info:', error);
    return NextResponse.json(
      { error: 'Failed to get system info' },
      { status: 500 }
    );
  }
}
