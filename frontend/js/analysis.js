/* analysis.js: AI chat client. Questions are answered by POST /api/v1/chat, which computes every
   number with pandas on the uploaded dataset (nothing is generated or invented by the frontend). */
const Analysis = {
    connected: true,
    /** Returns {answer, charts:[{title,figure,config,notes}], table, columns_used} */
    async ask(datasetId, question, filters = []) {
        const res = await Api.chat(datasetId, question, filters);
        return res;
    }
};
