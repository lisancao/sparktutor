/**
 * Sidebar TreeDataProvider: shows courses and their lessons with progress icons.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { CourseMeta, CourseProgress } from "./types";

type TreeNode = CourseNode | LessonNode;

class CourseNode extends vscode.TreeItem {
  constructor(
    public readonly course: CourseMeta,
    public progress: CourseProgress
  ) {
    super(course.title, vscode.TreeItemCollapsibleState.Expanded);
    this.description = `${course.lessonCount} lessons`;
    this.tooltip = course.description;
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
      title: "Open Lesson",
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
      } catch {
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
  // Remove leading number prefix like "01_" "02_"
  const stripped = lessonId.replace(/^\d+_/, "");
  // Convert underscores to spaces and title-case
  const words = stripped.split("_").map(
    (w) => w.charAt(0).toUpperCase() + w.slice(1)
  );
  return `${idx + 1}. ${words.join(" ")}`;
}
