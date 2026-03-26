import { NextRequest, NextResponse } from 'next/server';
import { updateTaskStatus } from '@/lib/db';

export async function POST(
  _request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const success = updateTaskStatus(params.id, 'queued');
    if (!success) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }
    return NextResponse.json({ success: true, status: 'queued' });
  } catch (error) {
    console.error('Error redispatching task:', error);
    return NextResponse.json(
      { error: 'Failed to redispatch task' },
      { status: 500 }
    );
  }
}
