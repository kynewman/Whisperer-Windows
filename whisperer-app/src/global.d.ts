declare global {
  interface Window {
    whisperer?: {
      minimize: () => void;
      maximize: () => void;
      close: () => void;
      showWindow?: () => void;
      startDrag?: () => void;
      startResize?: () => void;
      startEngine?: () => void;
      stopEngine?: () => void;
      engineState?: () => Promise<string>;
      appSnapshot?: () => Promise<string>;
      vocabularySnapshot?: () => Promise<string>;
      searchVocabulary?: (query: string) => Promise<string>;
      historySnapshot?: () => Promise<string>;
      modesSnapshot?: () => Promise<string>;
      micLevel?: () => Promise<string>;
      setModel?: (value: string) => Promise<string>;
      setGpu?: (value: string) => Promise<string>;
      modelCacheStatus?: (value: string) => Promise<string>;
      setApiKey?: (service: string, value: string) => Promise<string>;
      testApiKey?: (service: string) => Promise<string>;
      setMicrophone?: (value: string) => Promise<string>;
      setInputChannel?: (value: string) => Promise<string>;
      addVocabularyWord?: (word: string) => Promise<string>;
      addReplacementRule?: (matchText: string, replaceWith: string) => Promise<string>;
      copyText?: (text: string) => Promise<string>;
      transcribeLastDictation?: () => Promise<string>;
      runSttBenchmark?: () => Promise<string>;
      deleteDictation?: (dictationId: number) => Promise<string>;
      purgeHistory?: () => Promise<string>;
      addMode?: (name?: string) => Promise<string>;
      deleteMode?: (modeId: number) => Promise<string>;
      updateMode?: (modeId: number, patch: Record<string, unknown>) => Promise<string>;
      addAutoRule?: (modeId: number, type: string, value: string, priority: number) => Promise<string>;
      deleteAutoRule?: (ruleId: number) => Promise<string>;
      setShortcut?: (name: string, value: string) => Promise<string>;
      setSetting?: (section: string, key: string, value: unknown) => Promise<string>;
      checkForUpdates?: () => Promise<string>;
      installUpdate?: () => Promise<string>;
    };
  }
}
export {};
