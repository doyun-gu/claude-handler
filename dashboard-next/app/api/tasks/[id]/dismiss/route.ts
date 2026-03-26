import { NextRequest, NextResponse } from 'next/server';
import { updateTaskStatus } from '@/lib/db';

export async function POST(
  _request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const success = updateTaskStatus(params.id, 'dismissed');
    if (!success) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }
    return NextResponse.json({ success: true, status: 'dismissed' });
  } catch (error) {
    console.error('Error dismissing task:', error);
    return NextResponse.json(
      { error: 'Failed to dismiss task' },
      { status: 500 }
    );
  }
}
