/**
 * Sidebar TreeDataProvider: shows courses and their lessons with progress icons.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { SparkOutputChannel } from "./outputChannel";
import { CourseMeta, CourseProgress } from "./types";

type TreeNode = CourseNode | LessonNode;

class CourseNode extends vscode.TreeItem {
  constructor(
    public readonly course: CourseMeta,
    public progress: CourseProgress
  ) {
    super(course.title, vscode.TreeItemCollapsibleState.Expanded);
    this.description = `${course.lessonCount} 节课`;
    if (course.prerequisites?.length) {
      this.tooltip = course.description + "\n\n前置要求：\n" +
        course.prerequisites.map(p => `• ${p}`).join("\n");
    } else {
      this.tooltip = course.description;
    }
    this.contextValue = "course";
  }
}

class LessonNode extends vscode.TreeItem {
  constructor(
    public readonly courseId: string,
    public readonly lessonId: string,
    public readonly lessonIdx: number,
    label: string,
    public readonly status: "completed" | "in-progress" | "not-started"
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.contextValue = "lesson";

    switch (status) {
      case "completed":
        this.iconPath = new vscode.ThemeIcon(
          "pass-filled",
          new vscode.ThemeColor("testing.iconPassed")
        );
        break;
      case "in-progress":
        this.iconPath = new vscode.ThemeIcon(
          "circle-filled",
          new vscode.ThemeColor("charts.orange")
        );
        break;
      default:
        this.iconPath = new vscode.ThemeIcon("circle-outline");
    }

    this.command = {
      command: "sparktutor.openLesson",
      title: "打开课程",
      arguments: [courseId, lessonIdx],
    };
  }
}

export class CourseTreeProvider
  implements vscode.TreeDataProvider<TreeNode>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<
    TreeNode | undefined
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private courses: CourseMeta[] = [];
  private progressMap = new Map<string, CourseProgress>();
  private retryCount = 0;

  constructor(private bridge: Bridge) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  async getChildren(element?: TreeNode): Promise<TreeNode[]> {
    if (!element) {
      // Root: list courses
      try {
        const result = await this.bridge.call<{ courses: CourseMeta[] }>(
          "listCourses"
        );
        this.retryCount = 0;
        this.courses = result.courses;

        // Fetch progress for each course
        const nodes: CourseNode[] = [];
        for (const course of this.courses) {
          try {
            const progress = await this.bridge.call<CourseProgress>(
              "getCourseProgress",
              { courseId: course.id }
            );
            this.progressMap.set(course.id, progress);
            nodes.push(new CourseNode(course, progress));
          } catch {
            nodes.push(
              new CourseNode(course, { started: false })
            );
          }
        }
        return nodes;
      } catch (err) {
        // Log the failure so it is visible in the SparkTutor output channel,
        // then retry a few times: the tree view can render before the Python
        // server is fully ready, and without a refresh the tree would stay
        // empty forever.
        const message = err instanceof Error ? err.message : String(err);
        const channel = new SparkOutputChannel();
        channel.appendLine(`[tree] listCourses failed: ${message}`);
        if (this.retryCount < 3) {
          this.retryCount++;
          setTimeout(() => this.refresh(), 2000);
        }
        return [];
      }
    }

    if (element instanceof CourseNode) {
      const course = element.course;
      const progress = this.progressMap.get(course.id) || {
        started: false,
      };

      return course.lessons.map((lessonId, idx) => {
        let status: "completed" | "in-progress" | "not-started" = "not-started";
        if (progress.started) {
          const completedCount = progress.lessonsCompleted || 0;
          const currentIdx = progress.currentLessonIdx || 0;
          if (idx < completedCount) {
            status = "completed";
          } else if (idx === currentIdx) {
            status = "in-progress";
          }
        }

        // Format lesson name: "01_spark_session" → "1. Spark Session"
        const label = formatLessonName(lessonId, idx);
        return new LessonNode(course.id, lessonId, idx, label, status);
      });
    }

    return [];
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    return element;
  }
}

function formatLessonName(lessonId: string, idx: number): string {
  // Chinese display names, kept in sync with lesson.yaml "Lesson:" titles
  const CN_LESSON_NAMES: Record<string, string> = {
    // learning_spark
    "01_getting_started": "简介与快速上手",
    "02_dataframes_schemas": "DataFrame 与 Schema",
    "03_data_sources": "数据源与格式",
    "04_external_sources_hof": "复杂类型与高阶函数",
    "05_spark_sql_deep_dive": "Spark SQL 与 Catalyst 优化器",
    "06_optimization_tuning": "性能优化与调优",
    "07_join_strategies": "Join 策略",
    "08_structured_streaming": "Structured Streaming 结构化流处理",
    "09_data_lakes": "数据湖与湖仓",
    "10_mllib": "用 MLlib 进行机器学习",
    // spark_declarative_pipelines
    "01_spark_session": "SparkSession 与管道搭建",
    "02_functions_and_transforms": "函数与转换",
    "03_reading_writing_data": "读写数据",
    "04_pipeline_framework": "管道框架",
    "05_bronze_layer": "Bronze 层",
    "06_silver_layer": "Silver 层",
    "07_gold_layer": "Gold 层",
    "08_full_pipeline": "完整管道",
  };

  const cn = CN_LESSON_NAMES[lessonId];
  if (cn) {
    return `${idx + 1}. ${cn}`;
  }

  // Fallback: remove leading number prefix like "01_" "02_"
  const stripped = lessonId.replace(/^\d+_/, "");
  // Convert underscores to spaces and title-case
  const words = stripped.split("_").map(
    (w) => w.charAt(0).toUpperCase() + w.slice(1)
  );
  return `${idx + 1}. ${words.join(" ")}`;
}
