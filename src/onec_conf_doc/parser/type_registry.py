"""Mapping between 1C export folders and metadata object types."""

from __future__ import annotations

FOLDER_TO_TYPE: dict[str, str] = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "Enums": "Enum",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "CommonModules": "CommonModule",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "ExchangePlans": "ExchangePlan",
    "DocumentJournals": "DocumentJournal",
    "Sequences": "Sequence",
    "Constants": "Constant",
    "DefinedTypes": "DefinedType",
    "Roles": "Role",
    "Subsystems": "Subsystem",
    "CommonForms": "CommonForm",
    "CommonCommands": "CommonCommand",
    "CommonAttributes": "CommonAttribute",
    "FunctionalOptions": "FunctionalOption",
    "ScheduledJobs": "ScheduledJob",
    "WebServices": "WebService",
    "HTTPServices": "HTTPService",
}

TYPE_TO_FOLDER: dict[str, str] = {v: k for k, v in FOLDER_TO_TYPE.items()}

REGISTER_TYPES: frozenset[str] = frozenset(
    {
        "InformationRegister",
        "AccumulationRegister",
        "AccountingRegister",
        "CalculationRegister",
    }
)

TYPE_LABELS_RU: dict[str, str] = {
    "Catalog": "Справочник",
    "Document": "Документ",
    "Enum": "Перечисление",
    "InformationRegister": "Регистр сведений",
    "AccumulationRegister": "Регистр накопления",
    "AccountingRegister": "Регистр бухгалтерии",
    "CalculationRegister": "Регистр расчёта",
    "Report": "Отчёт",
    "DataProcessor": "Обработка",
    "CommonModule": "Общий модуль",
    "ChartOfAccounts": "План счетов",
    "ChartOfCharacteristicTypes": "План видов характеристик",
    "ChartOfCalculationTypes": "План видов расчёта",
    "BusinessProcess": "Бизнес-процесс",
    "Task": "Задача",
    "ExchangePlan": "План обмена",
    "DocumentJournal": "Журнал документов",
    "Sequence": "Последовательность",
    "Constant": "Константа",
    "DefinedType": "Определяемый тип",
    "Role": "Роль",
    "Subsystem": "Подсистема",
    "CommonForm": "Общая форма",
    "CommonCommand": "Общая команда",
    "CommonAttribute": "Общий реквизит",
    "FunctionalOption": "Функциональная опция",
    "ScheduledJob": "Регламентное задание",
    "WebService": "Web-сервис",
    "HTTPService": "HTTP-сервис",
    "Configuration": "Конфигурация",
}
