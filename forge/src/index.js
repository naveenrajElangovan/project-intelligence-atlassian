import api, { storage } from "@forge/api";
import crypto from "node:crypto";

function resource(event) {
  const issue = event.issue || {};
  const comment =
    event.comment ||
    (String(event.eventType || "").endsWith(":comment") ? event.content || {} : {});
  const worklog = event.worklog || {};
  const attachment = event.attachment || {};
  const content = event.content || attachment.container || {};
  if (comment.id)
    return [
      "COMMENT",
      String(comment.id),
      String(issue.id || comment.container?.id || comment.content?.id || ""),
      String(issue.fields?.project?.key || comment.space?.id || comment.content?.space?.id || ""),
    ];
  if (worklog.id)
    return [
      "WORKLOG",
      String(worklog.id),
      String(issue.id || worklog.issueId || ""),
      String(issue.fields?.project?.key || ""),
    ];
  if (attachment.id)
    return [
      "ATTACHMENT",
      String(attachment.id),
      String(issue.id || attachment.container?.id || attachment.issueId || ""),
      String(issue.fields?.project?.key || attachment.space?.id || ""),
    ];
  if (issue.id) return ["ISSUE", String(issue.id), null, issue.fields?.project?.key || ""];
  return [
    content.type === "blogpost" ? "BLOGPOST" : "PAGE",
    String(content.id || ""),
    null,
    String(content.space?.id || ""),
  ];
}

function resources(event) {
  if (event.sourceIssueId && event.destinationIssueId) {
    const linkId = String(event.id || "link");
    return [
      ["ISSUE_LINK", linkId, String(event.sourceIssueId), String(event.sourceProjectId || "")],
      [
        "ISSUE_LINK",
        linkId,
        String(event.destinationIssueId),
        String(event.destinationProjectId || ""),
      ],
    ];
  }
  return [resource(event)];
}

function cloudId(context) {
  if (context.cloudId) return String(context.cloudId);
  const installContext = String(context.installContext || "");
  return installContext.includes("/") ? installContext.split("/").pop() : "";
}

export async function run(event, context) {
  const callback = await storage.get("callback");
  const url = callback?.url;
  if (!url) return;
  const secret = process.env.FORGE_WEBHOOK_SECRET;
  if (!secret) throw new Error("FORGE_WEBHOOK_SECRET is not configured");
  for (const [resourceType, resourceId, parentResourceId, projectOrSpaceId] of resources(event)) {
    if (!resourceId) continue;
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const eventId = crypto
      .createHash("sha256")
      .update(
        JSON.stringify([
          event.eventType,
          event.eventCreatedDate,
          resourceType,
          resourceId,
          parentResourceId,
        ]),
      )
      .digest("hex");
    const payload = JSON.stringify({
      eventId,
      eventType: event.eventType,
      eventCreatedAt: event.eventCreatedDate || new Date().toISOString(),
      cloudId: cloudId(context),
      resourceType,
      resourceId,
      parentResourceId: parentResourceId || null,
      projectOrSpaceId,
      selfGenerated: Boolean(event.selfGenerated),
    });
    const signature = `sha256=${crypto.createHmac("sha256", secret).update(`${timestamp}.${payload}`).digest("hex")}`;
    const response = await api.fetch(`${url.replace(/\/$/, "")}/v1/events/atlassian`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-atlassian-timestamp": timestamp,
        "x-atlassian-signature-256": signature,
      },
      body: payload,
    });
    if (!response.ok) throw new Error(`Event forwarding failed: ${response.status}`);
  }
}

export async function configure(request) {
  const expected = process.env.FORGE_CONFIG_SECRET;
  const authorization =
    request.headers?.authorization?.[0] || request.headers?.Authorization?.[0] || "";
  if (!expected || authorization !== `Bearer ${expected}`) {
    return {
      statusCode: 401,
      headers: { "content-type": ["application/json"] },
      body: JSON.stringify({ error: "unauthorized" }),
    };
  }
  const body = JSON.parse(request.body || "{}");
  if (typeof body.url !== "string" || !body.url.startsWith("https://")) {
    return {
      statusCode: 422,
      headers: { "content-type": ["application/json"] },
      body: JSON.stringify({ error: "invalid callback" }),
    };
  }
  await storage.set("callback", { url: body.url, updatedAt: new Date().toISOString() });
  return { statusCode: 204, headers: {}, body: "" };
}
