export interface Task {
  id: string;
  slug: string;
  branch: string;
  project_name: string;
  project_path: string;
  subdir: string;
  status: TaskStatus;
  prompt: string;
  prompt_file: string;
  budget_usd: number;
  max_turns: number;
  permission_mode: string;
  tmux_session: string;
  base_branch: string;
  priority: number;
  depends_on: string;
  group_name: string;
  retry_count: number;
  max_retries: number;
  merged_from: string;
  pid: number;
  pgid: number;
  dispatched_at: string;
  started_at: string;
  finished_at: string;
  last_heartbeat: string;
  last_log_size: number;
  pr_url: string;
  error_message: string;
  cost_usd: number;
  eval_result: string;
  eval_rounds: number;
  eval_score: number;
  eval_cost_usd: number;
  route: string;
  created_at: string;
  updated_at: string;
}

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'dismissed'
  | 'merged'
  | 'cancelled';

export interface TaskStats {
  counts: Record<string, number>;
  total: number;
  today_cost: number;
  total_cost: number;
  stuck_count: number;
  completed_today: number;
}
