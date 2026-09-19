import { BuildGridHarness } from '../../../components/BuildGrid';

const UUIDS = {
  ruleFolder: 'uuid-rule-folder',
  expressionRule: 'uuid-expression-rule',
  interface: 'uuid-interface',
  processFolder: 'uuid-process-folder',
  processModel: 'uuid-process-model',
  recordType: 'uuid-record-type',
  integration: 'uuid-integration',
};

const CODEBASE = {
  by_type: {
    rule_folder: [UUIDS.ruleFolder],
    expression_rule: [UUIDS.expressionRule],
    interface: [UUIDS.interface],
    process_model_folder: [UUIDS.processFolder],
    process_model: [UUIDS.processModel],
    record_type: [UUIDS.recordType],
    integration: [UUIDS.integration],
  },
  uuid_to_name: {
    [UUIDS.ruleFolder]: 'Rules',
    [UUIDS.expressionRule]: 'APP_CalculateTotal',
    [UUIDS.interface]: 'APP_RequestForm',
    [UUIDS.processFolder]: 'Processes',
    [UUIDS.processModel]: 'APP_RequestApproval',
    [UUIDS.recordType]: 'APP_Request',
    [UUIDS.integration]: 'APP_SubmitRequest',
  },
  descriptions: {
    [UUIDS.expressionRule]: 'Calculates the request total',
    [UUIDS.interface]: 'Form used to submit a request',
    [UUIDS.processModel]: 'Routes a request for approval',
    [UUIDS.recordType]: 'Request business data',
    [UUIDS.integration]: 'Sends a request to the service',
  },
};

const PARENT_BY_UUID = {
  [UUIDS.expressionRule]: UUIDS.ruleFolder,
  [UUIDS.processModel]: UUIDS.processFolder,
  [UUIDS.interface]: 'uuid-folder-not-in-export',
};

const REVERSE_DEPENDENCIES = {
  [UUIDS.expressionRule]: [UUIDS.interface],
  [UUIDS.recordType]: [UUIDS.interface, UUIDS.processModel],
  [UUIDS.integration]: [UUIDS.processModel],
};

export default function BuildGridHarnessPage() {
  return (
    <BuildGridHarness
      codebase={CODEBASE}
      parentByUuid={PARENT_BY_UUID}
      reverseDependencies={REVERSE_DEPENDENCIES}
    />
  );
}
