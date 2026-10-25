export function iconMarkup(name) {
  return `<svg aria-hidden="true"><use href="#icon-${name}"/></svg>`;
}

export function avatarMarkup(isAI) {
  return iconMarkup(isAI ? 'robot' : 'person');
}
