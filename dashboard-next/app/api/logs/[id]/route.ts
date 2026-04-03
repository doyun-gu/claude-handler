import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import os from 'os';

export const dynamic = 'force-dynamic';

const LOGS_DIR = path.join(os.homedir(), '.claude-fleet', 'logs');

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const { searchParams } = new URL(request.url);
    const tail = parseInt(searchParams.get('tail') || '100', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    const logFile = path.join(LOGS_DIR, `${params.id}.log`);
    const summaryFile = path.join(LOGS_DIR, `${params.id}.summary.md`);

    let log = '';
    let summary = '';
    let totalSize = 0;

    if (fs.existsSync(logFile)) {
      const stats = fs.statSync(logFile);
      totalSize = stats.size;

      if (offset > 0) {
        // Read from offset for live tailing
        const fd = fs.openSync(logFile, 'r');
        const buffer = Buffer.alloc(Math.min(stats.size - offset, 64 * 1024));
        fs.readSync(fd, buffer, 0, buffer.length, offset);
        fs.closeSync(fd);
        log = buffer.toString('utf8');
      } else {
        // Read last N lines
        const content = fs.readFileSync(logFile, 'utf8');
        const lines = content.split('\n');
        log = lines.slice(-tail).join('\n');
      }
    }

    if (fs.existsSync(summaryFile)) {
      summary = fs.readFileSync(summaryFile, 'utf8');
    }

    return NextResponse.json({
      log,
      summary,
      totalSize,
    });
  } catch (error) {
    console.error('Error reading log:', error);
    return NextResponse.json(
      { error: 'Failed to read log' },
      { status: 500 }
    );
  }
}
