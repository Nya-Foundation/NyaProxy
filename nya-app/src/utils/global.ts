import type { App, Plugin } from 'vue';

export const withInstall = <T>(component: T, alias?: string) => {
  const comp = component as Recordable;
  comp.install = (app: App) => {
    app.component(comp.name ?? comp.displayName, comp);
    if (alias) {
      app.config.globalProperties[alias] = component;
    }
  };
  return component as T & Plugin;
};

export const converToArray = (number: number): Array<number> =>
  [...`${number}`].map(el => parseInt(el));
