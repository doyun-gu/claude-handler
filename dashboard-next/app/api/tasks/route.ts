import { NextRequest, NextResponse } from 'next/server';
import { listTasks, getRecentTasks } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get('status') || undefined;
    const recent = searchParams.get('recent');

    let tasks;
    if (recent) {
      tasks = getRecentTasks(parseInt(recent, 10) || 24);
    } else {
      tasks = listTasks(status, 200);
    }

    return NextResponse.json({ tasks });
  } catch (error) {
    console.error('Error fetching tasks:', error);
    return NextResponse.json(
      { error: 'Failed to fetch tasks' },
      { status: 500 }
    );
  }
}
