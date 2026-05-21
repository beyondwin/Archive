import Ajv from "ajv";
import addFormats from "ajv-formats";
import { schemas, type ContractSchemaName } from "./schemas";

export class ContractValidationError extends Error {
  readonly schemaName: string;
  readonly validationErrors: unknown[];

  constructor(schemaName: string, validationErrors: unknown[]) {
    super(`Contract ${schemaName} failed validation`);
    this.name = "ContractValidationError";
    this.schemaName = schemaName;
    this.validationErrors = validationErrors;
  }
}

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

const validators = new Map(
  Object.entries(schemas).map(([name, schema]) => [name, ajv.compile(schema)])
);

export function validateContract<T = unknown>(schemaName: ContractSchemaName, value: unknown): T {
  const validator = validators.get(schemaName);
  if (!validator) {
    throw new Error(`Unknown contract schema ${schemaName}`);
  }
  if (!validator(value)) {
    throw new ContractValidationError(schemaName, validator.errors ?? []);
  }
  return value as T;
}

export function isContract(schemaName: ContractSchemaName, value: unknown): boolean {
  try {
    validateContract(schemaName, value);
    return true;
  } catch {
    return false;
  }
}
