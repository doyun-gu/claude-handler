import { NextRequest, NextResponse } from 'next/server';
import { listTasks, updateTaskStatus } from '@/lib/db';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { action } = body;

    if (action === 'dismiss-all-failed') {
      const failed = listTasks('failed');
      let count = 0;
      for (const task of failed) {
        if (updateTaskStatus(task.id, 'dismissed')) count++;
      }
      return NextResponse.json({ success: true, count });
    }

    if (action === 'redispatch-all-failed') {
      const failed = listTasks('failed');
      let count = 0;
      for (const task of failed) {
        if (updateTaskStatus(task.id, 'queued')) count++;
      }
      return NextResponse.json({ success: true, count });
    }

    return NextResponse.json({ error: 'Unknown action' }, { status: 400 });
  } catch (error) {
    console.error('Error in bulk action:', error);
    return NextResponse.json(
      { error: 'Failed to perform bulk action' },
      { status: 500 }
    );
  }
}
