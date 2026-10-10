const asciiAlphanumeric = /^[A-Za-z0-9]+$/;

function pathParts(path) {
  const separator = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return {
    parent: separator < 0 ? "" : separator === 0 ? path[0] : path.slice(0, separator),
    separator: separator < 0 ? "\\" : path[separator],
    name: path.slice(separator + 1),
  };
}

function fileExtension(name) {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot) : "";
}

export function collisionKey(path) {
  return path.replace(/[\\/]+$/, "").toLocaleLowerCase("en-US");
}

export function validateManualCandidate(rawName, record, existingItems, completedTargets) {
  if (!/^[A-Za-z0-9 ]*$/.test(rawName)) {
    return { error: "Use only A-Z, a-z, 0-9, and spaces." };
  }
  const name = rawName.trim();
  if (!name) return { error: "Name cannot be empty." };
  if (!/^[A-Za-z0-9 ]+$/.test(name)) {
    return { error: "Use only A-Z, a-z, 0-9, and spaces." };
  }
  if (!asciiAlphanumeric.test(name.replaceAll(" ", ""))) {
    return { error: "Name must include at least one letter or number." };
  }

  const source = pathParts(record.path);
  const extension = record.kind === "folder" ? "" : fileExtension(record.name || source.name);
  const parentPrefix = source.parent
    ? source.parent.endsWith(source.separator) ? source.parent : `${source.parent}${source.separator}`
    : "";
  const targetPath = `${parentPrefix}${name}${extension}`;
  const targetKey = collisionKey(targetPath);
  const sourceKey = collisionKey(record.path);
  const alreadyUsed = completedTargets.has(targetKey);
  const alreadyExists = existingItems.some((item) =>
    collisionKey(item.path) === targetKey && collisionKey(item.path) !== sourceKey
  );

  if (alreadyUsed) return { error: "That name was already used by another manual rename." };
  if (alreadyExists) return { error: "A file or folder with that name already exists." };
  return { name, targetPath, targetKey };
}
